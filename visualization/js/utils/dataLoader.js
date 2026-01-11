/**
 * SPARC Data Loader Utilities
 * Binary Pack Loader (ZIP STORED of .npy files)
 * Minimal ZIP reader (STORED entries only) + NPY parser to produce typed arrays
 */

/**
 * Decode UTF-8 bytes to string
 * @param {Uint8Array} u8 - Byte array to decode
 * @returns {string} Decoded string
 */
export function decodeUTF8(u8) {
    try {
        return new TextDecoder('utf-8').decode(u8);
    } catch {
        // Fallback (very rare)
        let s = '';
        for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
        return decodeURIComponent(escape(s));
    }
}

/**
 * Parse a ZIP file with STORED (uncompressed) entries only
 * @param {ArrayBuffer} arrayBuffer - ZIP file contents
 * @returns {Object} Object with getFile(name) and list() methods
 */
export function parseZipStored(arrayBuffer) {
    const u8 = new Uint8Array(arrayBuffer);
    const dv = new DataView(arrayBuffer);

    // Find End of Central Directory (EOCD) by scanning last 64KB
    const EOCD_SIG = 0x06054b50;
    const maxScan = Math.min(u8.length, 0xFFFF + 22);
    let eocdOffset = -1;
    for (let i = u8.length - 22; i >= u8.length - maxScan; i--) {
        if (dv.getUint32(i, true) === EOCD_SIG) {
            eocdOffset = i;
            break;
        }
    }
    if (eocdOffset < 0) throw new Error('Invalid ZIP: EOCD not found');

    const cdSize = dv.getUint32(eocdOffset + 12, true);
    const cdOffset = dv.getUint32(eocdOffset + 16, true);

    // Parse central directory
    const CEN_SIG = 0x02014b50;
    const entries = {};
    let ptr = cdOffset;
    const end = cdOffset + cdSize;
    while (ptr < end) {
        const sig = dv.getUint32(ptr, true);
        if (sig !== CEN_SIG) throw new Error('Invalid ZIP: central directory signature mismatch');
        const compress = dv.getUint16(ptr + 10, true);
        const compSize = dv.getUint32(ptr + 20, true);
        const uncompSize = dv.getUint32(ptr + 24, true);
        const nameLen = dv.getUint16(ptr + 28, true);
        const extraLen = dv.getUint16(ptr + 30, true);
        const commentLen = dv.getUint16(ptr + 32, true);
        const localHeaderOffset = dv.getUint32(ptr + 42, true);
        const nameBytes = u8.subarray(ptr + 46, ptr + 46 + nameLen);
        const name = decodeUTF8(nameBytes);
        // Move to next entry
        ptr = ptr + 46 + nameLen + extraLen + commentLen;

        // Read local header to find data offset
        const LOC_SIG = 0x04034b50;
        if (dv.getUint32(localHeaderOffset, true) !== LOC_SIG) throw new Error('Invalid ZIP: local header signature mismatch');
        const locNameLen = dv.getUint16(localHeaderOffset + 26, true);
        const locExtraLen = dv.getUint16(localHeaderOffset + 28, true);
        const dataOffset = localHeaderOffset + 30 + locNameLen + locExtraLen;

        entries[name] = {
            compression: compress,
            compressedSize: compSize,
            uncompressedSize: uncompSize,
            dataOffset,
        };
    }

    // Only support STORED entries (no compression)
    for (const k in entries) {
        if (entries[k].compression !== 0) {
            throw new Error('Compressed ZIP entries are not supported in this viewer. Please export with uncompressed pack.');
        }
    }

    return {
        getFile(name) {
            const e = entries[name];
            if (!e) return null;
            return new Uint8Array(arrayBuffer, e.dataOffset, e.uncompressedSize);
        },
        list() {
            return Object.keys(entries);
        }
    };
}

/**
 * Map numpy dtype string to TypedArray constructor
 * @param {string} descr - Numpy dtype descriptor
 * @returns {TypedArrayConstructor} Appropriate TypedArray constructor
 */
export function dtypeToTypedArrayConstructor(descr) {
    // Endianness is little ('<') in our files
    if (descr.endsWith('f8') || descr.endsWith('f64')) return Float64Array;
    if (descr.endsWith('f4') || descr.endsWith('f32')) return Float32Array;
    if (descr.endsWith('i1')) return Int8Array;
    if (descr.endsWith('u1')) return Uint8Array;
    if (descr.endsWith('i2')) return Int16Array;
    if (descr.endsWith('u2')) return Uint16Array;
    if (descr.endsWith('i4')) return Int32Array;
    if (descr.endsWith('u4')) return Uint32Array;
    // 64-bit ints: use BigInt arrays if needed; most series fit in Number range
    if (descr.endsWith('i8')) return BigInt64Array;
    if (descr.endsWith('u8')) return BigUint64Array;
    // Fallback
    return Float64Array;
}

/**
 * Parse a NumPy .npy file
 * @param {Uint8Array} u8 - NPY file contents
 * @returns {Object} Object with data (TypedArray), shape, and dtype
 */
export function parseNPY(u8) {
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    // Magic: '\x93NUMPY'
    if (!(u8[0] === 0x93 && u8[1] === 0x4e && u8[2] === 0x55 && u8[3] === 0x4d && u8[4] === 0x50 && u8[5] === 0x59)) {
        throw new Error('Invalid NPY: bad magic');
    }
    const major = u8[6];
    let headerLen, headerStart;
    if (major === 1) {
        headerLen = dv.getUint16(8, true); headerStart = 10;
    } else {
        headerLen = dv.getUint32(8, true); headerStart = 12;
    }
    const headerTxt = new TextDecoder('ascii').decode(u8.subarray(headerStart, headerStart + headerLen));
    // Parse minimal dict: descr, fortran_order, shape
    const descrMatch = headerTxt.match(/'descr'\s*:\s*'([^']+)'/);
    const shapeMatch = headerTxt.match(/'shape'\s*:\s*\(([^\)]*)\)/);
    const fortranMatch = headerTxt.match(/'fortran_order'\s*:\s*(True|False)/);
    if (!descrMatch || !shapeMatch || !fortranMatch) throw new Error('Invalid NPY header');
    const descr = descrMatch[1];
    const fortran = fortranMatch[1] === 'True';
    const shapeParts = shapeMatch[1].split(',').map(s => s.trim()).filter(Boolean).map(s => parseInt(s, 10));
    const shape = shapeParts.length ? shapeParts : [parseInt(shapeMatch[1], 10)];
    const dataOffset = headerStart + headerLen;

    const ctor = dtypeToTypedArrayConstructor(descr);
    const numel = shape.reduce((a, b) => a * b, 1);
    const byteLen = numel * ctor.BYTES_PER_ELEMENT;
    const elementSize = ctor.BYTES_PER_ELEMENT;
    const actualOffset = u8.byteOffset + dataOffset;

    // Check if offset is aligned to element size (required for typed arrays)
    const needsCopy = (actualOffset % elementSize) !== 0;

    let dataView;
    if (needsCopy || fortran) {
        // Copy to aligned buffer (required for alignment or Fortran-order conversion)
        const alignedData = new Uint8Array(byteLen);
        alignedData.set(u8.subarray(dataOffset, dataOffset + byteLen));
        dataView = new ctor(alignedData.buffer, alignedData.byteOffset, numel);

        if (fortran && shape.length > 1) {
            // Convert Fortran-order to C-order copy
            const cpy = new ctor(numel);
            // Only handle 2D efficiently (our use-case)
            if (shape.length === 2) {
                const R = shape[0], C = shape[1];
                let idx = 0;
                for (let r = 0; r < R; r++) {
                    for (let c = 0; c < C; c++) {
                        cpy[idx++] = dataView[c * R + r];
                    }
                }
            } else {
                // Generic (slower) fallback
                for (let i = 0; i < numel; i++) cpy[i] = dataView[i];
            }
            return { data: cpy, shape, dtype: descr };
        }
        return { data: dataView, shape, dtype: descr };
    } else {
        // Offset is aligned, can use view directly
        dataView = new ctor(u8.buffer, actualOffset, numel);
        return { data: dataView, shape, dtype: descr };
    }
}

/**
 * Load a SPARC binary pack file (.npz/.zip)
 * @param {File} file - File object to load
 * @returns {Promise<Object>} Parsed simulation data
 */
export async function loadSparcPack(file) {
    const ab = await file.arrayBuffer();
    const zip = parseZipStored(ab);
    const names = zip.list();
    const out = {};

    // Metadata
    const headerBytes = zip.getFile('header.json');
    if (headerBytes) {
        const header = JSON.parse(decodeUTF8(headerBytes));
        // Extract metadata from header object
        if (header.metadata) {
            out.metadata = header.metadata;
        }
    }

    for (const name of names) {
        if (!name.endsWith('.npy')) continue;
        const base = name.replace(/\.npy$/, '');
        const u8 = zip.getFile(name);
        const parsed = parseNPY(u8);
        if (Array.isArray(parsed.shape) && parsed.shape.length > 1) {
            out[base] = { data: parsed.data, shape: parsed.shape, dtype: parsed.dtype };
        } else {
            out[base] = parsed.data;
        }
    }

    // Normalize expected names (aliases) if needed
    const T = (out.time && (Array.isArray(out.time) || ArrayBuffer.isView(out.time))) ? out.time.length : null;
    const pickAlias = (keys, pattern) => {
        if (!T) return null;
        // Prefer exact matches first
        for (const k of keys) {
            const v = out[k];
            if (v && (Array.isArray(v) || ArrayBuffer.isView(v)) && v.length === T) return v;
        }
        // Fallback: any key matching pattern
        for (const key of Object.keys(out)) {
            if (key === 'time' || key === 'metadata') continue;
            if (!pattern.test(key)) continue;
            const v = out[key];
            if (v && (Array.isArray(v) || ArrayBuffer.isView(v)) && v.length === T) return v;
        }
        return null;
    };
    if (!out.voltage) {
        const v = pickAlias(['voltage', 'voltage_V', 'V', 'voltage_signal', 'voltage_measured'], /volt|^V$/i);
        if (v) out.voltage = v;
    }
    if (!out.current) {
        const i = pickAlias(['current', 'current_A', 'I', 'current_signal', 'current_measured'], /curr|^I$/i);
        if (i) out.current = i;
    }

    return out;
}
