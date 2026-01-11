import numpy as np

print('=== NEW FORMAT (smoke_test_position_control.npz) ===')
new = np.load('c:/Users/GonzalezSanchezEduar/Repositorios/SPARC/logs/smoke_test_position_control.npz', allow_pickle=True)
print('Keys:', list(new.keys()))
for k in new.keys():
    arr = new[k]
    if isinstance(arr, bytes):
        print(f'{k}: bytes, len={len(arr)}')
    else:
        print(f'{k}: shape={arr.shape}, dtype={arr.dtype}')
        if len(arr) > 0 and k in ['wire_temperature', 'wire_material_positions_mm', 'wire_damage']:
            first = arr[0]
            print(f'  First element type: {type(first)}, len: {len(first) if hasattr(first, "__len__") else "scalar"}')
