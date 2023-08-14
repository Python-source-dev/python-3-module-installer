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


Instruction
------------
<details>
  <summary>1. Create file "install.py" in needed directory</summary>
  
![alt text](https://downloader.disk.yandex.ru/preview/0235fbd15e7ec0b26f90f2a80935e61e89df0572ecad6d009139c25658b3fce2/64d55395/iA_1u4ujWUcmzOBmOKRwtb_lybIQbDByhbVcvWnDbrlIYYObFDu7quXYclv4yhIQz_6v2pS4EFk0ILdrbdbNMw%3D%3D?uid=0&filename=2023-08-10_20-15-15.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)
![alt text](https://downloader.disk.yandex.ru/preview/1605df921d82ea993000363f496952d766965d912b3bb5d147707bc678c67142/64d55497/aKVGJ-14kMQQzdRvvnF1wJJh_pjTCokqL8a_l8HNz8cxq--7ozbljK4h_JZUKeIuxviiBz_vTQFhFAPbxXV8mg%3D%3D?uid=0&filename=2023-08-10_20-18-26.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)
</details>


<details>
  <summary>2. Copy and paste code below</summary>

![alt_text](https://downloader.disk.yandex.ru/preview/6b304b771c5dbb88c3546612e12f198cdbec4c0279c5e5e089c2e9341d2b7495/64d55564/dCTCH_ho22FI4FekYIIlcdJ6b7FmasDcAADZq8mRX9SHmeEdF1xT9PVg6zQjBq8VQUKqwfidJfCr_e8D0O6rQA%3D%3D?uid=0&filename=2023-08-10_20-22-44.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)

```python
from intaller.install import ModuleInstaller

install = ModuleInstaller({})
install.install_modules(path_to_folder="absolute path to folder")
```
   and press CTRL + S (Save file)
</details>


<details>
  <summary>3. Get needed path to folder.</summary>
   Click right mouse button and click "Copy path"
   

![alt_text](https://downloader.disk.yandex.ru/preview/31b07d1ef35e68567aeab06ae80baf47864f85e8e23f0448f213f158f09a2c49/64d5560d/SVqPdcGkDamkJ8eLH0eZCfAnfKG6nyf7FmKBEzpzB1XKGx1HhEB_dTylQ12PMg2SUf40nnmBJE63qfhqY5Efaw%3D%3D?uid=0&filename=2023-08-10_20-26-02.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)

</details>

<details>
  <summary>4. Past path into line 4 in install.py (install.install_modules(path_to_folder="absolute path to folder")).</summary>


![alt_text](https://downloader.disk.yandex.ru/preview/50298680d514b318da42a8b0831bcae646068c68dad22d4391477959a43d1009/64d556e2/iHwYS6KkLqtHa-rS0zUESlywuvzLE_iOxW9kqM4ySvamxEeomwE2_LgRPy_zgIkv-NzkfzDF8XSGG6LbaHbPrA%3D%3D?uid=0&filename=2023-08-10_20-29-41.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)

4.1 Delete "\install.py" in path because it requires path to folder, not to file

![alt_text](https://downloader.disk.yandex.ru/preview/a51ec36bdde24c79bb4c29a4560dde4a601ba313a8b466bbd7e340ce14ec0f03/64d55770/E_UOwIZw9_6_3hGlnPz0Nn-NT01TYytURtlRCjOV6HhsUMtUZ1WX_XuJqRUJ7pZ2XpTxQoCqcT3fYdxgLExjWA%3D%3D?uid=0&filename=2023-08-10_20-32-07.png&disposition=inline&hash=&limit=0&content_type=image%2Fpng&owner_uid=0&tknv=v2&size=2048x2048)
</details>
Now save the file and run script! Script will install all requested frameworks.

# For Contributors

### Prepare development environment
1. Install docker on your development machine
1. Start server for testing by following commands from the project's root folder or change path to `conf` dir in second command to correct:
```shell script
docker pull bytemark/installer
docker run -d --name installer -e AUTH_TYPE=Basic -e USERNAME=alice -e PASSWORD=secret1234 -v conf:/usr/local/apache2/conf -p 8585:80 bytemark/installer
``` 

### Code convention

Please check your code according PEP8 Style guides.

### Run tests
1. Check that installer container is started on your local machine
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
