from setuptools import find_packages, setup

setup(
    name='co_location',
    packages=find_packages(),
    version='1.5.3',
    description='Physcis project. Kubernertes Collocation library',
    author='Ainhoa Azqueta-Alzúaz',
    author_email='aazqueta@fi.upm.es',
    license='MIT',
    install_requires=['kubernetes', 'prometheus_api_client', 'prometheus_client'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest==4.4.1'],
    test_suite='tests',
    python_requires='>=3.7',
    download_url='https://github.com/physics-faas/co-location/archive/refs/tags/v1.5.3.tar.gz'
)