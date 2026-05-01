"""
LightHermes 命令行界面

提供交互式对话界面
"""

import sys
import os
import yaml
from pathlib import Path

from lighthermes.core import LightHermes

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
        self.session_id = None
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
        model_config = self.config.get("model", {})
        memory_config = self.config.get("memory", {})
        evolution_config = self.config.get("evolution", {})
        skills_config = self.config.get("skills", {})
        cli_config = self.config.get("cli", {})

        api_key = model_config.get("api_key")
        if api_key and api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var)

        self.agent = LightHermes(
            name="LightHermes",
            role="你是 LightHermes,一个轻量级自进化智能体助手",
            model=model_config.get("model_name", "gpt-4o-mini"),
            provider=model_config.get("provider", "openai"),
            api_key=api_key,
            base_url=model_config.get("base_url"),
            memory_enabled=memory_config.get("enabled", True),
            memory_dir=memory_config.get("storage_dir", "memory"),
            evolution_enabled=evolution_config.get("enabled", True),
            auto_generate_skills=evolution_config.get("auto_generate_skills", True),
            skill_validation=evolution_config.get("skill_validation", "sandbox"),
            skill_dirs=skills_config.get("dirs", ["skills/core", "skills/user", "skills/generated"]),
            debug=cli_config.get("show_skill_usage", False)
        )

        self.cli_config = cli_config

    def print_banner(self):
        """打印启动横幅"""
        if not self.cli_config.get("show_banner", True):
            return

        self._print("╭─────────────────────────────────────╮", "cyan", "bright")
        self._print("│  LightHermes v0.2.0                │", "cyan", "bright")
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

        episodic_count = len(list(Path(self.agent.memory.episodic.storage_dir).glob("*.md")))
        print(f"  情景记忆: {episodic_count} 个项目/任务")

        semantic_count = len(list(Path(self.agent.memory.semantic.storage_dir).glob("*.md")))
        print(f"  语义记忆: {semantic_count} 条知识")
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

            episodic_count = len(list(Path(self.agent.memory.episodic.storage_dir).glob("*.md")))
            print(f"  情景记忆: {self._colorize(str(episodic_count), 'cyan')} 个项目/任务")

            semantic_count = len(list(Path(self.agent.memory.semantic.storage_dir).glob("*.md")))
            print(f"  语义记忆: {self._colorize(str(semantic_count), 'cyan')} 条知识")

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

    def reset_session(self):
        """重置会话但保留记忆"""
        if self.agent.memory_enabled:
            self.agent.memory.short_term.messages = []

        self.agent.query_count = 0
        self.agent.api_call_count = 0
        self.agent.total_tokens_used = 0

        if self.agent.compression_enabled:
            self.agent.compressor.compression_count = 0
            self.agent.compressor.tokens_saved = 0

        self._print("\n✓ 会话已重置", "green")
        print("  短期记忆已清空，长期记忆保留")
        print()

    def clear_screen(self):
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def handle_command(self, cmd: str) -> bool:
        """处理命令,返回是否继续"""
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
            return False

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
                self._print("\n\n再见!", "cyan")
                break
            except EOFError:
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
