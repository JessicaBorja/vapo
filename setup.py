from setuptools import setup

setup(name='project',
      version='1.0',
      description='Python Distribution Utilities',
      packages=['vapo'],
      install_requires=[
          'hydra-core(==1.1.1)',
          'opencv-python(==4.5.3.56)',
          'pybullet(==3.1.7)',
          'hydra-colorlog',
          'matplotlib']
     )