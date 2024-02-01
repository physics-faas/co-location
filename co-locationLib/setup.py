from setuptools import find_packages, setup

# read the contents of your README file
from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name='co_location',
    packages=find_packages(),
    version='1.5.4',
    description='Physcis project. Kubernertes Collocation library',
    author='Ainhoa Azqueta-Alzúaz',
    author_email='aazqueta@fi.upm.es',
    license='MIT',
    install_requires=['kubernetes', 'prometheus_api_client', 'prometheus_client'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest==4.4.1'],
    test_suite='tests',
    python_requires='>=3.7',
    download_url='https://github.com/physics-faas/co-location/archive/refs/tags/v.1.5.4.tar.gz',
    long_description=long_description,
    long_description_content_type='text/markdown'
)