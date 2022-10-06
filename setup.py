#    Copyright 2022 Google LLC
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
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
    description="Circuit analysis helper",
    long_description=long_description,
    long_description_content_type="text/markdown",
    package_data={'': ['LICENSE']},
    ##url="https://???",
    author="Arya Reais-Parsi",
    author_email="growly@google.com",
    packages=find_packages(),
    ##python_requires=">=3.8, <4",
    install_requires=["pyverilog", "numpy", "matplotlib", "protobuf>4.21"],
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
