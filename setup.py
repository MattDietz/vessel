from setuptools import setup, find_packages

setup(name='vessel',
      version='1.7.0',
      description='Agnostic Dev Env CLI',
      url='https://www.github.com/cerberus/vessel',
      packages=find_packages(exclude=['examples', 'tests']),
      install_requires=[],
      tests_require=[
          'nose',
          'coverage',
          'mock'],
      entry_points={
        "console_scripts": [
            "vessel = vessel:run",
        ]})
