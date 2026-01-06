from setuptools import setup, find_packages

setup(
    name="sc2rl",
    version="0.1.0",
    description="StarCraft II Reinforcement Learning Gym",
    packages=find_packages(),
    install_requires=[
        "pysc2>=3.0.0",
        "gymnasium>=0.28.0",
        "stable-baselines3>=2.0.0",
        "torch>=2.0.0",
        "numpy>=1.24.0",
        "pyyaml>=6.0",
    ],
    python_requires=">=3.8",
)
