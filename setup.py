from setuptools import setup

__version__ = '0.1'

setup(
    name='PyARL',
    version=__version__,
    packages=['pyarl'],
    url='',
    license='',
    author='Joshua Laughner',
    author_email='jlaugh@caltech.edu',
    description='Python tools to work with ARL files',
    entry_points={
        'console_scripts': ['wrf2arl-multi=pyarl.wrf2arl:main',
                            'link-reinit-arl=pyarl.wrf2arl:link_main']
    },
    install_requires=['configobj >= 5.0.0']  # earlier versions of configobj may well work
)
