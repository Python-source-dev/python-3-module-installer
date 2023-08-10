Package installer 
=========
[![PyPI](https://img.shields.io/pypi/v/python-module-installer)](https://pypi.org/project/python-module-installer/) ![PyPI - Python Version](https://img.shields.io/pypi/pyversions/python-module-installer)  
This package helps you to install all modules you need in your directory

Installation
------------
```bash
$ pip install python-module-installer
```

Sample Usage
------------

```python
from intaller.install import ModuleInstaller

install = ModuleInstaller({})
install.install_modules(path_to_folder="absolute path to folder")
```


# For Contributors

### Prepare development environment
1. Install docker on your development machine
1. Start server for testing by following commands from the project's root folder or change path to `conf` dir in second command to correct:
```shell script
docker pull bytemark/webdav
docker run -d --name webdav -e AUTH_TYPE=Basic -e USERNAME=alice -e PASSWORD=secret1234 -v conf:/usr/local/apache2/conf -p 8585:80 bytemark/webdav
``` 

### Code convention

Please check your code according PEP8 Style guides.

### Run tests
1. Check that webdav container is started on your local machine
1. Execute following command in the project's root folder:
```shell script
python -m unittest discover -s tests
```

### Prepare a Pull Request

Please use this check list before creating PR:
1. You code should be formatted according PEP8
1. All tests should successfully pass
1. Your changes shouldn't change previous default behaviour, exclude defects
1. All changes are covered by tests 
