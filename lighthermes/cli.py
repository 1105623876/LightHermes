"""
LightHermes 命令行界面

提供交互式对话界面
"""

import sys
import os
import yaml
import uuid
import json
from pathlib import Path

from lighthermes.core import LightHermes
from lighthermes.runtime_memory import DEFAULT_USER_ID

# 修复 Windows 终端编码问题
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 尝试导入 colorama，如果不存在则禁用彩色输出
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    COLORS_AVAILABLE = True
except ImportError:
    COLORS_AVAILABLE = False
    # 定义空的颜色常量
    class Fore:
        GREEN = CYAN = YELLOW = RED = BLUE = MAGENTA = ""
    class Style:
        BRIGHT = RESET_ALL = ""


class CLI:
    """命令行界面"""

    def __init__(self):
        self.agent = None
        self.config = self.load_config()
        self.session_id = uuid.uuid4().hex
        self.cli_config = {}

    def _use_color(self) -> bool:
        """判断是否使用彩色输出"""
        return self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE

    def _colorize(self, text: str, color: str = "", style: str = "") -> str:
        """返回彩色文本（如果启用）"""
        if not self._use_color():
            return text
        color_code = getattr(Fore, color.upper(), "")
        style_code = getattr(Style, style.upper(), "")
        return f"{color_code}{style_code}{text}{Style.RESET_ALL}"

    def _print(self, text: str, color: str = "", style: str = ""):
        """打印文本（支持彩色）"""
        print(self._colorize(text, color, style))

    def load_config(self, config_path: str = "config.yaml") -> dict:
        """加载配置文件"""
        if not os.path.exists(config_path):
            return {}

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def init_agent(self):
        """初始化 Agent"""
        cli_config = self.config.get("cli", {})

        self.agent = LightHermes.from_config(
            config_path="config.yaml",
            name="LightHermes",
            role="你是 LightHermes,一个轻量级自进化智能体助手",
            debug=cli_config.get("show_skill_usage", False)
        )

        self.cli_config = cli_config

    def authorize_bash(self):
        """Authorize local execution once per CLI session, never from model input."""
        executor = getattr(self.agent, "bash", None)
        if executor is None:
            return
        executor.authorized = False
        if not sys.stdin.isatty():
            self._print("bash 未授权：非交互 CLI 不执行本机命令。", "yellow")
            return
        self._print(f"bash 工作目录：{executor.cwd}（本机执行，非沙箱）", "yellow")
        answer = input("允许本会话在当前任务范围内执行 bash？[y/N] ").strip().lower()
        executor.authorized = answer in {"y", "yes"}

    def print_banner(self):
        """打印启动横幅"""
        if not self.cli_config.get("show_banner", True):
            return

        self._print("╭─────────────────────────────────────╮", "cyan", "bright")
        self._print("│  LightHermes v0.3.4                │", "cyan", "bright")
        self._print("│  轻量级自进化智能体框架              │", "cyan", "bright")
        self._print("╰─────────────────────────────────────╯", "cyan", "bright")
        print()

    def print_help(self):
        """打印帮助信息"""
        self._print("\n可用命令:", "yellow")
        commands = [
            ("/help", "显示帮助信息"),
            ("/skills", "列出所有可用技能"),
            ("/memory", "显示记忆系统统计"),
            ("/experiences", "查看当前范围候选/已激活经验（需 evolution.enabled）"),
            ("/learn <success|failure|unknown|used-success|used-failure> <验证说明>", "回答后记录真实验证；首次最多一次提炼请求"),
            ("/trial <ID> <任务>", "只在这个任务试用指定经验"),
            ("/approve <ID> <理由>", "确认已验证复用的经验适用范围"),
            ("/revoke <ID> <理由>", "撤回经验并退出召回"),
            ("/stats", "显示详细统计信息"),
            ("/config", "显示当前配置"),
            ("/compress", "压缩当前对话上下文"),
            ("/export", "导出对话历史"),
            ("/reset", "重置会话但保留记忆"),
            ("/clear", "清屏"),
            ("/exit", "退出")
        ]
        for cmd, desc in commands:
            cmd_colored = self._colorize(cmd, "green")
            print(f"  {cmd_colored:20s} - {desc}")
        print()

    def show_skills(self):
        """显示所有技能"""
        skills = self.agent.skill_loader.get_all_skills()
        if not skills:
            print("\n暂无可用技能")
            return

        self._print("\n可用技能:", "yellow")
        for skill in skills:
            status = self._colorize("✓", "green")
            name = self._colorize(skill['name'], "cyan")
            print(f"  {status} {name} - {skill['description']}")
        print()

    def show_memory_stats(self):
        """显示记忆统计"""
        if not self.agent.memory_enabled:
            print("\n记忆系统未启用")
            return

        print("\n记忆系统统计:")
        print(f"  短期记忆: {len(self.agent.memory.short_term.messages)} 条消息")

        usage = self.agent.memory.store.usage()
        print(f"  受管理磁盘: {usage['managed_bytes']} / {usage['max_bytes']} bytes")
        print(f"  事件: {usage['events']['count']} 条，正文 {usage['events']['logical_bytes']} bytes")
        for status, item in usage['entries'].items():
            print(f"  {status}: {item['count']} 条，正文 {item['logical_bytes']} bytes")
        print('  正文字节不含数据库开销；归档不会自动释放磁盘。')
        print()

    def show_config(self):
        """显示当前配置"""
        print("\n当前配置:")
        print(f"  模型: {self.agent.model}")
        print(f"  记忆系统: {'启用' if self.agent.memory_enabled else '禁用'}")
        print(f"  自进化: {'启用' if self.agent.evolution_enabled else '禁用'}")
        print(f"  上下文压缩: {'启用' if self.agent.compression_enabled else '禁用'}")
        print()

    def show_compression_stats(self):
        """显示压缩统计"""
        if not self.agent.compression_enabled:
            print("\n上下文压缩未启用")
            return

        stats = self.agent.compressor.get_stats()
        self._print("\n上下文压缩统计:", "yellow")
        print(f"  压缩次数: {self._colorize(str(stats['compression_count']), 'cyan')}")
        print(f"  节省 tokens: {self._colorize(str(stats['tokens_saved']), 'cyan')}")
        print(f"  平均每次节省: {self._colorize(str(stats['avg_tokens_saved']), 'cyan')}")
        print()

    def manual_compress(self):
        """手动触发压缩"""
        if not self.agent.compression_enabled:
            print("\n上下文压缩未启用")
            return

        if not self.agent.memory_enabled:
            print("\n需要启用记忆系统才能使用压缩功能")
            return

        messages = self.agent.memory.short_term.messages
        if len(messages) < 5:
            print("\n对话消息太少，无需压缩")
            return

        self._print("\n正在压缩对话上下文...", "yellow")

        original_count = len(messages)
        compressed = self.agent.compressor.compress(messages)
        self.agent.memory.short_term.messages = compressed
        new_count = len(compressed)

        self._print("✓ 压缩完成", "green")
        print(f"  消息数: {self._colorize(str(original_count), 'cyan')} → {self._colorize(str(new_count), 'cyan')}")
        print()

    def show_stats(self):
        """显示详细统计信息"""
        self._print("\n会话统计:", "yellow")
        print(f"  API 调用次数: {self._colorize(str(self.agent.api_call_count), 'cyan')}")
        print(f"  Token 使用: {self._colorize(str(self.agent.total_tokens_used), 'cyan')}")
        print(f"  查询次数: {self._colorize(str(self.agent.query_count), 'cyan')}")

        if self.agent.memory_enabled:
            self._print("\n记忆统计:", "yellow")
            print(f"  短期记忆: {self._colorize(str(len(self.agent.memory.short_term.messages)), 'cyan')} 条消息")

            self.show_memory_stats()

        if self.agent.compression_enabled:
            stats = self.agent.compressor.get_stats()
            self._print("\n压缩统计:", "yellow")
            print(f"  压缩次数: {self._colorize(str(stats['compression_count']), 'cyan')}")
            print(f"  节省 tokens: {self._colorize(str(stats['tokens_saved']), 'cyan')}")
        print()

    def export_history(self):
        """导出对话历史"""
        if not self.agent.memory_enabled:
            print("\n需要启用记忆系统才能导出历史")
            return

        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chat_history_{timestamp}.json"

        history = {
            "timestamp": timestamp,
            "messages": self.agent.memory.short_term.messages,
            "stats": {
                "api_calls": self.agent.api_call_count,
                "tokens_used": self.agent.total_tokens_used,
                "query_count": self.agent.query_count
            }
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        self._print("\n✓ 对话历史已导出", "green")
        print(f"  文件: {self._colorize(filename, 'cyan')}")
        print()

    def end_session(self):
        """触发会话结束生命周期"""
        if not (self.agent and self.agent.memory_enabled and self.agent.memory):
            return

        messages = self.agent.memory.short_term.messages
        if not messages:
            return

        summary = "\n".join(
            f"{msg.get('role', '')}: {str(msg.get('content', ''))[:200]}"
            for msg in messages[-10:]
        )
        try:
            self.agent.memory.on_session_end(
                self.session_id,
                DEFAULT_USER_ID,
                summary=summary
            )
        except Exception as e:
            self._print(f"\n会话保存失败，当前会话尚未重置: {e}", "red")
            return False
        return True

    def reset_session(self):
        """重置会话但保留记忆"""
        if self.end_session() is False:
            return
        self.session_id = uuid.uuid4().hex
        if self.agent.memory_enabled:
            self.agent.memory.short_term.messages = []

        self.agent.query_count = 0
        self.agent.api_call_count = 0
        self.agent.total_tokens_used = 0

        if self.agent.compression_enabled:
            self.agent.compressor.compression_count = 0
            self.agent.compressor.tokens_saved = 0

        self.authorize_bash()
        self._print("\n✓ 会话已重置", "green")
        print("  短期记忆已清空，长期记忆保留")
        print()

    def clear_screen(self):
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def handle_command(self, cmd: str) -> bool:
        """处理命令,返回是否继续"""
        if cmd.split(maxsplit=1) and cmd.split(maxsplit=1)[0] in {'/learn', '/trial', '/approve', '/revoke', '/experiences'}:
            try:
                parts = cmd.split(maxsplit=2)
                action = parts[0]
                if action == '/experiences':
                    result = self.agent.experiences()
                else:
                    if len(parts) != 3:
                        raise ValueError('请提供状态或 ID，以及具体验证说明/任务/理由；见 /help')
                    if action == '/learn':
                        outcomes = {'success': 'verified_success', 'failure': 'verified_failure',
                                    'unknown': 'unknown', 'used-success': 'verified_success', 'used-failure': 'verified_failure'}
                        if parts[1] not in outcomes:
                            raise ValueError('未知验证状态；见 /help')
                        self._print('记录宿主/用户验证；首次学习最多请求一次模型提炼，不重试。', 'yellow')
                        result = self.agent.learn(parts[2], outcome=outcomes[parts[1]], adopted=parts[1].startswith('used-'))
                    elif action == '/trial':
                        result = self.agent.run(parts[2], session_id=self.session_id, trial_experience=parts[1])
                    else:
                        result = self.agent.review_experience(parts[1], action=action[1:], reason=parts[2])
                self._print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
            except (ValueError, KeyError) as exc:
                self._print(str(exc), 'red')
            return True
        commands = {
            "/help": self.print_help,
            "/skills": self.show_skills,
            "/memory": self.show_memory_stats,
            "/config": self.show_config,
            "/stats": self.show_stats,
            "/compress": self.manual_compress,
            "/compress stats": self.show_compression_stats,
            "/export": self.export_history,
            "/reset": self.reset_session,
            "/clear": self.clear_screen,
        }

        if cmd == "/exit":
            return self.end_session() is False

        handler = commands.get(cmd)
        if handler:
            handler()
        else:
            self._print(f"未知命令: {cmd}", "red")
            print(f"{self._colorize('提示:', 'yellow')} 输入 {self._colorize('/help', 'green')} 查看可用命令")
        return True

    def run(self):
        """运行交互式 CLI"""
        try:
            self.init_agent()
        except Exception as e:
            self._print(f"✗ 初始化失败: {e}", "red")
            self._print("\n可能的原因:", "yellow")
            print(f"  1. {self._colorize('config.yaml', 'cyan')} 文件不存在或格式错误")
            print("  2. API key 未配置（检查 config.yaml 或环境变量）")
            print("  3. 网络连接问题")
            self._print("\n建议操作:", "yellow")
            print(f"  • 检查 {self._colorize('config.yaml', 'cyan')} 是否存在")
            print("  • 确认 API key 已正确设置")
            print(f"  • 尝试运行: {self._colorize('python -m lighthermes.cli', 'green')}")
            return

        self.print_banner()
        try:
            self.authorize_bash()
        except (EOFError, KeyboardInterrupt):
            return

        prompt_symbol = self.cli_config.get("prompt_symbol", ">")
        stream_output = self.cli_config.get("stream_output", True)

        agent_name = self._colorize(f"[{self.agent.name}]", "green")
        print(f"{agent_name} 你好!有什么可以帮你的?\n")

        while True:
            try:
                user_input = input(f"{prompt_symbol} ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        break
                    continue

                print(f"\n{agent_name} ", end="", flush=True)

                response = self.agent.run(
                    user_input,
                    stream=stream_output,
                    session_id=self.session_id
                )

                if stream_output:
                    for chunk in response:
                        print(chunk, end="", flush=True)
                    print("\n")
                else:
                    print(response)
                    print()

            except KeyboardInterrupt:
                self.end_session()
                self._print("\n\n再见!", "cyan")
                break
            except EOFError:
                self.end_session()
                break
            except Exception as e:
                self._print(f"\n✗ 错误: {e}", "red")
                print(f"{self._colorize('提示:', 'yellow')} 如果问题持续，请检查网络连接或 API 配置")
                if self.agent.debug:
                    import traceback
                    traceback.print_exc()


def main():
    """主入口"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
