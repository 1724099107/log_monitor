# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import time
import signal
import re
import configparser
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Union


# ========================== 工具模块（适配EXE打包）==========================
def restart_program() -> None:
    """重启程序（适配EXE，单窗口运行）"""
    print("\nℹ️  准备重启程序...", flush=True)
    try:
        # 若为EXE，sys.executable指向EXE路径；若为脚本，指向python.exe
        exe_path = Path(sys.executable).resolve()
        args = sys.argv[1:]
        restart_cmd = [str(exe_path)] + args

        if os.name == "nt":
            # EXE打包后无需Python解释器，直接启动
            subprocess.Popen(restart_cmd, shell=True)
        else:
            subprocess.Popen(restart_cmd)
        sys.exit(0)
    except Exception as e:
        print(f"❌ 重启失败：{e}", flush=True)
        input("按回车关闭...")
        sys.exit(1)


def set_windows_codepage(codepage: str = "65001") -> None:
    """设置CMD编码为UTF-8（适配EXE环境）"""
    print("🔧  正在配置CMD环境...", flush=True)
    if os.name == "nt":
        try:
            subprocess.run(f"chcp {codepage}", shell=True, check=True, capture_output=True, text=True)
            # 适配EXE的标准输出编码
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            print(f"✅  CMD编码已切换为UTF-8（代码页：{codepage}）", flush=True)
        except Exception as e:
            print(f"⚠️  切换CMD编码失败：{str(e)}，可能导致中文乱码", flush=True)
    else:
        print("✅  非Windows系统，无需切换编码", flush=True)


# ========================== 配置模块（适配EXE路径）==========================
# 关键：EXE运行时获取正确的配置文件路径（当前EXE所在目录）
def get_exe_dir() -> Path:
    """获取EXE或脚本所在目录（适配打包后环境）"""
    if getattr(sys, 'frozen', False):
        # 打包成EXE时，_MEIPASS是临时目录，实际应使用EXE所在目录
        return Path(sys.executable).parent.resolve()
    else:
        # 脚本运行时，使用脚本所在目录
        return Path(sys.argv[0]).parent.resolve()


_DEFAULT_CONFIG_PATH = get_exe_dir() / "config.ini"
_CORRUPT_BACKUP_PATH = _DEFAULT_CONFIG_PATH.with_suffix(".ini.corrupt")
_SUPPORTED_ENCODINGS = ["utf-8", "gbk", "gb2312", "utf-8-sig"]
_SUPPORTED_ERROR_HANDLES = ["replace", "ignore", "strict"]
_REQUIRED_SECTIONS = ["LogSource", "ReadConfig", "MonitorConfig", "DisplayConfig", "QuitConfig"]
_REQUIRED_PARAMS = {
    "LogSource": ["File_Path", "Wait_For_File", "Wait_Interval"],
    "ReadConfig": ["Chunk_Size", "Encoding", "Error_Handle"],
    "MonitorConfig": ["Interval_MS", "Read_Full_On_Truncate", "Truncate_Sensitivity"],
    "DisplayConfig": ["Show_Status", "Filter_ANSI_Code", "Log_Filter", "Exclude_Filter"],
    "QuitConfig": ["Auto_Close_Delay", "Show_Stats"]
}


class ConfigManager:
    def __init__(self, config_path: Path = _DEFAULT_CONFIG_PATH):
        print("\n📋  正在加载配置文件...", flush=True)
        self.config_path = config_path.resolve()
        self.config_parser = self._init_parser()
        self.config_corrupt = False
        self._load_and_repair_config()
        self.valid_params = self._validate_and_load_params()
        print(f"✅  配置文件加载完成", flush=True)

    def _init_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(
            allow_no_value=True,
            comment_prefixes=(';',),
            default_section="Default"
        )
        parser.optionxform = str  # 保留参数大小写
        return parser

    def _is_config_corrupt(self) -> bool:
        if not all(sec in self.config_parser.sections() for sec in _REQUIRED_SECTIONS):
            return True
        for sec, params in _REQUIRED_PARAMS.items():
            if not all(p in self.config_parser[sec] for p in params):
                return True
        return False

    def _create_default_config(self) -> None:
        print(f"📝  正在创建默认配置文件...", flush=True)
        self.config_parser["LogSource"] = {
            "; 日志文件绝对路径（Windows用\\，Linux用/）": "",
            "; 示例：D:\\logs\\latest.log 或 /home/logs/latest.log": "",
            "File_Path": r"D:\服务器\开服侠\server\logs\latest.log",
            "; 日志不存在时是否等待（True/False）": "",
            "Wait_For_File": "True",
            "; 等待间隔（秒）": "",
            "Wait_Interval": "5"
        }

        self.config_parser["ReadConfig"] = {
            "; 读取块大小（字节，4096-131072）": "",
            "Chunk_Size": "32768",
            "; 编码（utf-8/gbk，中文乱码用gbk）": "",
            "Encoding": "utf-8",
            "; 非法字符处理（replace/ignore/strict）": "",
            "Error_Handle": "replace"
        }

        self.config_parser["MonitorConfig"] = {
            "; 监控间隔（毫秒，500-5000）": "",
            "Interval_MS": "1000",
            "; 截断后是否读取完整日志（True/False）": "",
            "Read_Full_On_Truncate": "True",
            "; 截断灵敏度（字节）": "",
            "Truncate_Sensitivity": "1024"
        }

        self.config_parser["DisplayConfig"] = {
            "; 是否显示状态信息（True/False）": "",
            "Show_Status": "True",
            "; 是否过滤ANSI颜色码（True/False）": "",
            "Filter_ANSI_Code": "False",
            "; 包含关键词（逗号分隔）": "",
            "Log_Filter": "ERROR,WARN,INFO",
            "; 排除关键词（逗号分隔）": "",
            "Exclude_Filter": "DEBUG"
        }

        self.config_parser["QuitConfig"] = {
            "; 自动关闭延迟（秒，0-10）": "",
            "Auto_Close_Delay": "3",
            "; 是否显示统计信息（True/False）": "",
            "Show_Stats": "True"
        }

        # 确保目录存在（适配EXE权限）
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            self.config_parser.write(f, space_around_delimiters=True)
        print(f"✅  默认配置文件创建成功：{self.config_path}", flush=True)

    def _load_and_repair_config(self) -> None:
        if not self.config_path.exists():
            print(f"⚠️  未找到配置文件：{self.config_path}", flush=True)
            self._create_default_config()
            self.config_parser.read(self.config_path, encoding="utf-8")
            return

        try:
            print(f"📥  正在读取配置文件：{self.config_path}", flush=True)
            self.config_parser.read(self.config_path, encoding="utf-8")
        except configparser.ParsingError as e:
            self.config_corrupt = True
            print(f"❌  配置文件格式错误：{str(e)}", flush=True)
        except Exception as e:
            self.config_corrupt = True
            print(f"❌  读取配置文件失败：{str(e)}", flush=True)

        if not self.config_corrupt:
            self.config_corrupt = self._is_config_corrupt()

        if self.config_corrupt:
            print(f"⚠️  配置文件已损坏，开始修复...", flush=True)
            try:
                shutil.copy2(self.config_path, _CORRUPT_BACKUP_PATH)
                print(f"✅  损坏配置已备份到：{_CORRUPT_BACKUP_PATH}", flush=True)
            except Exception as e:
                print(f"❌  备份损坏配置失败：{str(e)}", flush=True)

            self._create_default_config()
            print(f"✅  新配置文件创建成功：{self.config_path}", flush=True)
            print("⚠️  5秒后重启程序以加载新配置...", flush=True)

            for i in range(5, 0, -1):
                print(f"{' ' * 30}重启倒计时：{i}秒", end='\r', flush=True)
                time.sleep(1)
            restart_program()

    def _get_param(self, sec: str, key: str, dtype: type, default: Union[str, int, float, bool]) -> Union[
        str, int, float, bool]:
        try:
            if sec not in self.config_parser:
                print(f"⚠️  配置段[{sec}]缺失，使用默认值：{key}={default}", flush=True)
                return default
            if dtype == bool:
                return self.config_parser.getboolean(sec, key)
            elif dtype == int:
                return self.config_parser.getint(sec, key)
            elif dtype == float:
                return self.config_parser.getfloat(sec, key)
            return self.config_parser.get(sec, key).strip()
        except (configparser.NoOptionError, ValueError) as e:
            print(f"⚠️  参数[{sec}.{key}]无效：{str(e)}，使用默认值：{default}", flush=True)
            return default

    def _validate_and_load_params(self) -> Dict[str, Union[Path, bool, int, float, List[str]]]:
        print("🔍  正在验证配置参数...", flush=True)
        defaults = {
            "File_Path": r"D:\服务器\开服侠\server\logs\latest.log",
            "Wait_For_File": True,
            "Wait_Interval": 5.0,
            "Chunk_Size": 32768,
            "Encoding": "utf-8",
            "Error_Handle": "replace",
            "Interval_MS": 1000.0,
            "Read_Full_On_Truncate": True,
            "Truncate_Sensitivity": 1024,
            "Show_Status": True,
            "Filter_ANSI_Code": False,
            "Log_Filter": "ERROR,WARN,INFO",
            "Exclude_Filter": "DEBUG",
            "Auto_Close_Delay": 3,
            "Show_Stats": True
        }

        return {
            "file_path": Path(self._get_param("LogSource", "File_Path", str, defaults["File_Path"])).resolve(),
            "wait_for_file": self._get_param("LogSource", "Wait_For_File", bool, defaults["Wait_For_File"]),
            "wait_interval": max(1.0,
                                 min(self._get_param("LogSource", "Wait_Interval", float, defaults["Wait_Interval"]),
                                     30.0)),
            "chunk_size": max(4096,
                              min(self._get_param("ReadConfig", "Chunk_Size", int, defaults["Chunk_Size"]), 131072)),
            "encoding": self._get_param("ReadConfig", "Encoding", str, defaults["Encoding"]) if self._get_param(
                "ReadConfig", "Encoding", str, defaults["Encoding"]) in _SUPPORTED_ENCODINGS else "utf-8",
            "error_handle": self._get_param("ReadConfig", "Error_Handle", str,
                                            defaults["Error_Handle"]) if self._get_param("ReadConfig", "Error_Handle",
                                                                                         str, defaults[
                                                                                             "Error_Handle"]) in _SUPPORTED_ERROR_HANDLES else "replace",
            "interval": max(0.1,
                            min(self._get_param("MonitorConfig", "Interval_MS", float, defaults["Interval_MS"]) / 1000,
                                5.0)),
            "read_full_on_truncate": self._get_param("MonitorConfig", "Read_Full_On_Truncate", bool,
                                                     defaults["Read_Full_On_Truncate"]),
            "truncate_sensitivity": max(128, min(self._get_param("MonitorConfig", "Truncate_Sensitivity", int,
                                                                 defaults["Truncate_Sensitivity"]), 4096)),
            "show_status": self._get_param("DisplayConfig", "Show_Status", bool, defaults["Show_Status"]),
            "filter_ansi": self._get_param("DisplayConfig", "Filter_ANSI_Code", bool, defaults["Filter_ANSI_Code"]),
            "include_keywords": list(set([k.strip() for k in self._get_param("DisplayConfig", "Log_Filter", str,
                                                                             defaults["Log_Filter"]).split(",") if
                                          k.strip()])),
            "exclude_keywords": list(set([k.strip() for k in self._get_param("DisplayConfig", "Exclude_Filter", str,
                                                                             defaults["Exclude_Filter"]).split(",") if
                                          k.strip()])),
            "auto_close_delay": max(0, min(self._get_param("QuitConfig", "Auto_Close_Delay", int,
                                                           defaults["Auto_Close_Delay"]), 10)),
            "show_stats": self._get_param("QuitConfig", "Show_Stats", bool, defaults["Show_Stats"])
        }


# ========================== 日志处理模块 ==========================
_CHAR_FIX_MAP = {
    "mainEx": "main",
    "Server threadEx": "Server thread",
    "Worker-Main-Ex": "Worker-Main-"
}


class LogProcessor:
    def __init__(self, filter_ansi: bool):
        print("\n⚙️  正在初始化日志处理器...", flush=True)
        self.filter_ansi = filter_ansi
        self.ansi_pattern = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])') if filter_ansi else None
        self.char_fix_pattern = re.compile('|'.join(re.escape(k) for k in _CHAR_FIX_MAP.keys()))
        self.include_keywords: List[str] = []
        self.exclude_keywords: List[str] = []
        print(f"✅  日志处理器初始化完成（ANSI过滤：{'开启' if filter_ansi else '关闭'}）", flush=True)

    def set_keywords(self, include: List[str], exclude: List[str]) -> None:
        self.include_keywords = include
        self.exclude_keywords = exclude
        print(f"📌  过滤关键词已设置：包含[{','.join(include)}] | 排除[{','.join(exclude)}]", flush=True)

    def clean(self, content: str) -> str:
        content = self.char_fix_pattern.sub(lambda m: _CHAR_FIX_MAP[m.group()], content)
        if self.filter_ansi and self.ansi_pattern:
            content = self.ansi_pattern.sub('', content)
        return content

    def filter(self, content: str) -> bool:
        for kw in self.exclude_keywords:
            if kw in content:
                return False
        return any(kw in content for kw in self.include_keywords) if self.include_keywords else True


# ========================== 监控核心模块 ==========================
_COLOR_CODES = {
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m", "blue": "\033[34m", "reset": "\033[0m"
}


class LogMonitor:
    def __init__(self):
        self.config = ConfigManager()
        self.params = self.config.valid_params
        self.processor = LogProcessor(self.params["filter_ansi"])
        self.processor.set_keywords(
            include=self.params["include_keywords"],
            exclude=self.params["exclude_keywords"]
        )

        self._file = None
        self._is_running = False
        self._last_file_size = 0
        self._stats: Dict[str, int] = {
            "logs": 0, "bytes": 0, "truncates": 0, "errors": 0
        }
        self._start_time = datetime.now()

    def _print_status(self, msg: str, color: str = "white") -> None:
        color_code = _COLOR_CODES.get(color, "")
        print(f"{color_code}[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}{_COLOR_CODES['reset']}", flush=True)

    def _validate_file(self) -> None:
        file_path = self.params["file_path"]

        while not file_path.exists():
            if self.params["wait_for_file"]:
                self._print_status(f"⚠️  日志文件不存在，{self.params['wait_interval']}秒后重试", "yellow")
                time.sleep(self.params["wait_interval"])
            else:
                raise FileNotFoundError(f"❌ 日志文件不存在：{file_path}")

        if not file_path.is_file():
            raise IsADirectoryError(f"❌ 路径不是文件：{file_path}")
        if not os.access(file_path, os.R_OK):
            raise PermissionError(f"❌ 无读取权限：{file_path}")

        self._print_status(f"✅ 日志文件验证通过：{file_path}", "green")

    def _open_file(self, read_full: bool = False) -> None:
        self._close_file()
        try:
            self._file = open(
                self.params["file_path"],
                'r',
                encoding=self.params["encoding"],
                errors=self.params["error_handle"],
                buffering=1
            )
            self._last_file_size = self.params["file_path"].stat().st_size
            self._print_status(f"ℹ️  日志文件打开成功（大小：{self._last_file_size:,}字节）", "blue")

            if read_full:
                self._print_status(f"ℹ️  加载完整日志...", "blue")
                total_bytes = 0
                while chunk := self._file.read(self.params["chunk_size"]):
                    total_bytes += len(chunk)
                    cleaned = self.processor.clean(chunk)
                    if self.processor.filter(cleaned):
                        print(cleaned, end='', flush=True)
                self._stats["bytes"] += total_bytes
                self._stats["logs"] += total_bytes // 100
                self._print_status(f"✅ 加载完成：{total_bytes:,}字节", "green")
            else:
                self._file.seek(0, os.SEEK_END)
                self._print_status(f"✅ 监控就绪（间隔：{self.params['interval'] * 1000:.0f}ms）", "green")
        except Exception as e:
            raise RuntimeError(f"❌ 打开文件失败：{e}")

    def _close_file(self) -> None:
        if self._file and not self._file.closed:
            try:
                self._file.close()
                self._print_status("ℹ️  文件句柄已关闭", "blue")
            except Exception as e:
                self._print_status(f"⚠️  关闭文件失败：{e}", "yellow")
                self._stats["errors"] += 1
        self._file = None

    def _detect_truncate(self) -> bool:
        try:
            current_size = self.params["file_path"].stat().st_size
            size_diff = abs(current_size - self._last_file_size)
            if current_size < self._last_file_size and size_diff >= self.params["truncate_sensitivity"]:
                self._stats["truncates"] += 1
                self._print_status(f"⚠️  日志截断（第{self._stats['truncates']}次）", "red")
                self._last_file_size = current_size
                return True
            self._last_file_size = current_size
            return False
        except Exception as e:
            self._print_status(f"⚠️  检测文件失败：{e}", "yellow")
            self._stats["errors"] += 1
            return False

    def _print_header(self) -> None:
        header = "\n" + "=" * 80 + "\n"
        header += f"📡  日志监控工具（EXE适配版）\n"
        header += f"📅  启动时间：{self._start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        header += f"📄  监控文件：{self.params['file_path']}\n"
        header += f"⚙️  配置：编码{self.params['encoding']} | 间隔{self.params['interval'] * 1000:.0f}ms\n"
        header += f"🎯  过滤：包含[{','.join(self.params['include_keywords'])}] | 排除[{','.join(self.params['exclude_keywords'])}]\n"
        header += "=" * 80 + "\n"
        print(header, flush=True)

    def _print_stats(self) -> None:
        if not self.params["show_stats"]:
            return
        runtime = (datetime.now() - self._start_time).total_seconds()
        stats = "\n" + "=" * 80 + "\n"
        stats += f"📊  监控统计：\n"
        stats += f"  - 运行时长：{int(runtime // 3600)}h{int((runtime % 3600) // 60)}m{int(runtime % 60)}s\n"
        stats += f"  - 处理日志：约{self._stats['logs']:,}条 | 总字节：{self._stats['bytes']:,}B\n"
        stats += f"  - 截断次数：{self._stats['truncates']} | 错误次数：{self._stats['errors']}\n"
        stats += "=" * 80 + "\n"
        print(stats, flush=True)

    def start(self) -> None:
        self._print_header()
        try:
            self._validate_file()
            self._open_file(read_full=False)
            self._is_running = True
            # 适配EXE的信号处理（Windows下部分信号可能无效）
            if os.name == "nt":
                signal.signal(signal.SIGINT, self.stop)
            else:
                signal.signal(signal.SIGTERM, self.stop)

            while self._is_running:
                if self._detect_truncate() and self.params["read_full_on_truncate"]:
                    self._open_file(read_full=True)
                    continue

                if self._file:
                    new_content = self._file.read(self.params["chunk_size"])
                    if new_content:
                        self._stats["bytes"] += len(new_content)
                        self._stats["logs"] += 1
                        cleaned = self.processor.clean(new_content)
                        if self.processor.filter(cleaned):
                            print(cleaned, end='', flush=True)

                time.sleep(self.params["interval"])
        except Exception as e:
            self._print_status(f"❌  监控异常：{e}", "red")
            self._stats["errors"] += 1
        finally:
            self.stop()

    def stop(self, signum: int = None, frame: object = None) -> None:
        if not self._is_running:
            return
        self._print_status("\nℹ️  停止监控...", "yellow")
        self._is_running = False
        self._close_file()
        self._print_stats()

        delay = self.params["auto_close_delay"]
        if delay > 0:
            self._print_status(f"ℹ️  {delay}秒后自动关闭...", "yellow")
            for i in range(delay, 0, -1):
                print(f"{' ' * 30}关闭倒计时：{i}秒", end='\r', flush=True)
                time.sleep(1)
        sys.exit(0)


# ========================== 程序入口（适配EXE）==========================
def main():
    # 确保EXE运行时使用正确的工作目录（当前EXE所在目录）
    os.chdir(get_exe_dir())

    try:
        print("🚀  启动日志监控工具（EXE适配版）...", flush=True)
        set_windows_codepage()
        monitor = LogMonitor()
        monitor.start()
    except Exception as e:
        print(f"❌  程序初始化失败：{e}", flush=True)
        input("\n按回车关闭...")
        sys.exit(1)


if __name__ == "__main__":
    main()