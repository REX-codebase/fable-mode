from setuptools import setup, find_packages

setup(
    name="fable-engine",
    version="1.3.0",
    description="Deterministic System 2 Cognitive Engine & Mechanical Time-Lock MCP Server for Antigravity",
    license="MIT",
    packages=find_packages(),
    py_modules=["fable_mode_entry", "fable_compressor"],
    package_data={"fable_mode": ["resources.json", "LICENSE"], "fable_engine": ["fable_session.json"]},
    python_requires=">=3.10",
    install_requires=[],
    entry_points={
        "console_scripts": [
            # Portable package-aware installer/runtime.
            "fable-mode=fable_mode.launcher:main",
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

