"""Setup configuration for WEDM Learning Environment."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

setup(
    name="wedm-learning-environment",
    version="0.2.0",
    author="Eduardo Gonzalez Sanchez",
    author_email="",  # Add your email if you want
    description="A Gymnasium environment for Wire Electrical Discharge Machining (Wire EDM) simulation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/geduardo/WEDM-Learning-Environment",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "wedm": [
            "data/*.json",
            "modules/*.json",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.21.0",
        "gymnasium>=0.28.0",
        "numba>=0.56.0",
        "matplotlib>=3.5.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "flake8>=4.0.0",
            "mypy>=0.950",
        ],
        "visualization": [
            "pygame>=2.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            # Add any command-line scripts here if needed
        ],
    },
)
