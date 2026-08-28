from setuptools import setup, find_packages

setup(
    name="fable-engine",
    version="1.2.0",
    description="Deterministic System 2 Cognitive Engine & Mechanical Time-Lock MCP Server for Antigravity",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[],
    entry_points={
        "console_scripts": [
            # Legacy V1 MCP entry point.
            "fable-engine=fable_engine.server:main",
            "fable-v1=fable_engine.server:main",
            # V2 process execution boundary.
            "fable-v2-broker=fable_v2.execution_broker:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)

