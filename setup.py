from setuptools import setup, find_packages

setup(
    name="lighthermes",
    version="0.1.0",
    description="轻量级自进化智能体框架",
    author="LightHermes Team",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "local": ["sentence-transformers>=2.0.0"],
        "cli": ["colorama>=0.4.0"],
    },
    entry_points={
        "console_scripts": [
            "lighthermes=lighthermes.cli:main",
        ],
    },
    python_requires=">=3.8",
)
