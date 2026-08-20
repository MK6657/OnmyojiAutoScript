# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import re
import ctypes
import os
from pathlib import Path

from module.logger import logger

class ConfigManager:

    @staticmethod
    def _config_root() -> Path:
        return (Path.cwd() / 'config').resolve()

    @staticmethod
    def _safe_config_path(name: str) -> Path:
        """Resolve a config name without allowing path traversal."""
        if not isinstance(name, str) or not name or name in {'.', '..'}:
            raise ValueError('invalid config name')
        if '\x00' in name or '/' in name or '\\' in name or ':' in name:
            raise ValueError('config name must be a single file name')
        root = ConfigManager._config_root()
        path = (root / f'{name}.json').resolve()
        if path.parent != root:
            raise ValueError('config path escapes the config directory')
        return path

    @staticmethod
    def _send_to_recycle_bin(path: Path) -> None:
        """Move a config to the Windows Recycle Bin, never permanently unlink it."""
        if os.name != 'nt':
            path.unlink()
            return

        class _SHFileOpStruct(ctypes.Structure):
            _fields_ = [
                ('hwnd', ctypes.c_void_p),
                ('wFunc', ctypes.c_uint),
                ('pFrom', ctypes.c_wchar_p),
                ('pTo', ctypes.c_wchar_p),
                ('fFlags', ctypes.c_ushort),
                ('fAnyOperationsAborted', ctypes.POINTER(ctypes.c_bool)),
                ('hNameMappings', ctypes.c_void_p),
                ('lpszProgressTitle', ctypes.c_wchar_p),
            ]

        source = ctypes.c_wchar_p(str(path) + '\x00\x00')
        aborted = ctypes.c_bool(False)
        operation = _SHFileOpStruct(
            None,
            0x0003,  # FO_DELETE
            source,
            None,
            0x0004 | 0x0010 | 0x0040 | 0x0400,  # silent, no confirm, undo, no error UI
            ctypes.pointer(aborted),
            None,
            None,
        )
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result or aborted.value:
            raise OSError(f'SHFileOperationW failed with code {result}')

    @staticmethod
    def all_script_files() -> list[str]:
        """
        获取所有的脚本文件 除了tmplate
        :return: ['oas1', 'oas2']
        """
        # 获取某个路径的所有json文件名
        config_path = ConfigManager._config_root()
        json_files = config_path.glob('*.json')
        result = []
        for json in json_files:
            if json.stem == 'template':
                continue
            result.append(json.stem)
        if len(result) == 0:
            # 如果没有脚本文件 则创建一个
            ConfigManager.copy(file='oas1', template='template')
            result.append('oas1')
        return result

    @staticmethod
    def all_json_file() -> list:
        """
        获取所有的json文件
        :return: ['oas1', 'oas2']
        """
        # 获取某个路径的所有json文件名
        config_path = Path.cwd() / 'config'
        json_files = config_path.glob('*.json')
        result = []
        for json in json_files:
            if json.stem == 'template':
                result.insert(0, json.stem)
            else:
                result.append(json.stem)
        return result

    @staticmethod
    def copy(file: str, template: str = 'template') -> bool:
        """
        复制一个配置文件
        :param file:  不带json后缀
        :param template:
        :return:
        """
        try:
            template_path = ConfigManager._safe_config_path(template)
            file_path = ConfigManager._safe_config_path(file)
        except ValueError as error:
            logger.error(f'invalid config name: {error}')
            return False
        if file_path.exists():
            logger.error(f'{file_path} is exists')
            return False

        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        logger.info(f'copy {template_path} to {file_path}')
        return True


    @staticmethod
    def generate_script_name() -> str:
        """
        生成一个新的配置的名字
        :return:
        """
        all_script_files = ConfigManager.all_script_files()
        if not all_script_files:
            return 'oas1'

        script_numbers = []
        for script_file in all_script_files:
            match = re.search(r'\d+', script_file)
            if match:
                script_number = int(match.group())
                script_numbers.append(script_number)

        if not script_numbers:
            return 'oas1'
        script_numbers.sort()
        new_script_number = script_numbers[-1] + 1
        return f'oas{new_script_number}'

    @staticmethod
    def rename(old_name: str, new_name: str) -> bool:
        """
        重命名一个配置文件
        :param old_name: 旧的配置文件名称
        :param new_name: 新的配置文件名称
        :return: True or False
        """
        try:
            old_path = ConfigManager._safe_config_path(old_name)
            new_path = ConfigManager._safe_config_path(new_name)
        except ValueError as error:
            logger.error(f'invalid config name: {error}')
            return False
        if not old_path.exists():
            logger.error(f'{old_path} is not exists')
            return False
        if new_path.exists():
            logger.error(f'{new_path} is exists')
            return False
        try:
            old_path.rename(new_path)
            logger.info(f'rename {old_path} to {new_path}')
            return True
        except Exception as e:
            logger.error(f'rename {old_path} to {new_path} failed: {e}')
            return False

    @staticmethod
    def delete(file: str) -> bool:
        """
        删除一个配置文件
        :param file:  不带json后缀
        :return: True or False
        """
        try:
            file_path = ConfigManager._safe_config_path(file)
        except ValueError as error:
            logger.error(f'invalid config name: {error}')
            return False
        if not file_path.exists():
            logger.error(f'{file_path} is not exists')
            return False
        try:
            ConfigManager._send_to_recycle_bin(file_path)
            logger.info(f'move {file_path} to Recycle Bin')
            return True
        except Exception as e:
            logger.error(f'delete {file_path} failed: {e}')
            return False
