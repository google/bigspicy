"""
# Setup Script

Derived from the setuptools sample project at
https://github.com/pypa/sampleproject/blob/main/setup.py

"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="bigspicy",
    version="0.1.0",
    description="Circuit analysis helper"
    long_description=long_description,
    long_description_content_type="text/markdown",
    ##url="https://???",
    author="Arya Reais-Parsi",
    author_email="growly@google.com",
    ##packages=find_packages(),
    ##python_requires=">=3.8, <4",
    install_requires=["pyverilog", "numpy", "matplotlib", "protobuf"],
    extras_require={
        "dev": [
            "pytest==5.2",
            "coverage",
            "pytest-cov",
            "black==19.10b0",
            "click==8.0.1",  # This is transitive on `black`, but required for the CLI to work
            "twine",
        ]
    },
)
