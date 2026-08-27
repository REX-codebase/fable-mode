from setuptools import setup, find_packages

setup(
    name="fable-engine",
    version="1.0.0",
    description="Deterministic System 2 Cognitive Engine & Mechanical Time-Lock MCP Server for Antigravity",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[],
    entry_points={
        "console_scripts": [
            "fable-engine=fable_engine.server:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
