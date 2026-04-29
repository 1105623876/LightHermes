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

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"{Fore.CYAN}{Style.BRIGHT}╭─────────────────────────────────────╮")
            print(f"│  LightHermes v0.2.0                │")
            print(f"│  轻量级自进化智能体框架              │")
            print(f"╰─────────────────────────────────────╯{Style.RESET_ALL}")
        else:
            print("╭─────────────────────────────────────╮")
            print("│  LightHermes v0.2.0                │")
            print("│  轻量级自进化智能体框架              │")
            print("╰─────────────────────────────────────╯")
        print()

    def print_help(self):
        """打印帮助信息"""
        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"\n{Fore.YELLOW}可用命令:{Style.RESET_ALL}")
            print(f"  {Fore.GREEN}/help{Style.RESET_ALL}       - 显示帮助信息")
            print(f"  {Fore.GREEN}/skills{Style.RESET_ALL}     - 列出所有可用技能")
            print(f"  {Fore.GREEN}/memory{Style.RESET_ALL}     - 显示记忆系统统计")
            print(f"  {Fore.GREEN}/config{Style.RESET_ALL}     - 显示当前配置")
            print(f"  {Fore.GREEN}/compress{Style.RESET_ALL}   - 压缩当前对话上下文")
            print(f"  {Fore.GREEN}/clear{Style.RESET_ALL}      - 清屏")
            print(f"  {Fore.GREEN}/exit{Style.RESET_ALL}       - 退出")
        else:
            print("\n可用命令:")
            print("  /help       - 显示帮助信息")
            print("  /skills     - 列出所有可用技能")
            print("  /memory     - 显示记忆系统统计")
            print("  /config     - 显示当前配置")
            print("  /compress   - 压缩当前对话上下文")
            print("  /clear      - 清屏")
            print("  /exit       - 退出")
        print()

    def show_skills(self):
        """显示所有技能"""
        skills = self.agent.skill_loader.get_all_skills()
        if not skills:
            print("\n暂无可用技能")
            return

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"\n{Fore.YELLOW}可用技能:{Style.RESET_ALL}")
            for skill in skills:
                status = f"{Fore.GREEN}✓{Style.RESET_ALL}"
                name = f"{Fore.CYAN}{skill['name']}{Style.RESET_ALL}"
                desc = skill["description"]
                print(f"  {status} {name} - {desc}")
        else:
            print("\n可用技能:")
            for skill in skills:
                status = "✓"
                name = skill["name"]
                desc = skill["description"]
                print(f"  {status} {name} - {desc}")
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

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"\n{Fore.YELLOW}上下文压缩统计:{Style.RESET_ALL}")
            print(f"  压缩次数: {Fore.CYAN}{stats['compression_count']}{Style.RESET_ALL}")
            print(f"  节省 tokens: {Fore.CYAN}{stats['tokens_saved']}{Style.RESET_ALL}")
            print(f"  平均每次节省: {Fore.CYAN}{stats['avg_tokens_saved']}{Style.RESET_ALL}")
        else:
            print("\n上下文压缩统计:")
            print(f"  压缩次数: {stats['compression_count']}")
            print(f"  节省 tokens: {stats['tokens_saved']}")
            print(f"  平均每次节省: {stats['avg_tokens_saved']}")
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

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"\n{Fore.YELLOW}正在压缩对话上下文...{Style.RESET_ALL}")
        else:
            print("\n正在压缩对话上下文...")

        original_count = len(messages)
        compressed = self.agent.compressor.compress(messages)
        self.agent.memory.short_term.messages = compressed
        new_count = len(compressed)

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"{Fore.GREEN}✓ 压缩完成{Style.RESET_ALL}")
            print(f"  消息数: {Fore.CYAN}{original_count}{Style.RESET_ALL} → {Fore.CYAN}{new_count}{Style.RESET_ALL}")
        else:
            print("✓ 压缩完成")
            print(f"  消息数: {original_count} → {new_count}")
        print()

    def clear_screen(self):
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')

    def handle_command(self, cmd: str) -> bool:
        """处理命令,返回是否继续"""
        if cmd == "/help":
            self.print_help()
        elif cmd == "/skills":
            self.show_skills()
        elif cmd == "/memory":
            self.show_memory_stats()
        elif cmd == "/config":
            self.show_config()
        elif cmd == "/compress":
            self.manual_compress()
        elif cmd == "/compress stats":
            self.show_compression_stats()
        elif cmd == "/clear":
            self.clear_screen()
        elif cmd == "/exit":
            return False
        else:
            if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
                print(f"{Fore.RED}未知命令: {cmd}{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}提示:{Style.RESET_ALL} 输入 {Fore.GREEN}/help{Style.RESET_ALL} 查看可用命令")
            else:
                print(f"未知命令: {cmd}")
                print("提示: 输入 /help 查看可用命令")
        return True

    def run(self):
        """运行交互式 CLI"""
        try:
            self.init_agent()
        except Exception as e:
            if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
                print(f"{Fore.RED}✗ 初始化失败: {e}{Style.RESET_ALL}")
                print(f"\n{Fore.YELLOW}可能的原因:{Style.RESET_ALL}")
                print(f"  1. {Fore.CYAN}config.yaml{Style.RESET_ALL} 文件不存在或格式错误")
                print(f"  2. API key 未配置（检查 config.yaml 或环境变量）")
                print(f"  3. 网络连接问题")
                print(f"\n{Fore.YELLOW}建议操作:{Style.RESET_ALL}")
                print(f"  • 检查 {Fore.CYAN}config.yaml{Style.RESET_ALL} 是否存在")
                print(f"  • 确认 API key 已正确设置")
                print(f"  • 尝试运行: {Fore.GREEN}python -m lighthermes.cli{Style.RESET_ALL}")
            else:
                print(f"✗ 初始化失败: {e}")
                print("\n可能的原因:")
                print("  1. config.yaml 文件不存在或格式错误")
                print("  2. API key 未配置（检查 config.yaml 或环境变量）")
                print("  3. 网络连接问题")
                print("\n建议操作:")
                print("  • 检查 config.yaml 是否存在")
                print("  • 确认 API key 已正确设置")
                print("  • 尝试运行: python -m lighthermes.cli")
            return

        self.print_banner()

        prompt_symbol = self.cli_config.get("prompt_symbol", ">")
        stream_output = self.cli_config.get("stream_output", True)

        if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
            print(f"{Fore.GREEN}[{self.agent.name}]{Style.RESET_ALL} 你好!有什么可以帮你的?\n")
        else:
            print(f"[{self.agent.name}] 你好!有什么可以帮你的?\n")

        while True:
            try:
                user_input = input(f"{prompt_symbol} ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        break
                    continue

                if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
                    print(f"\n{Fore.GREEN}[{self.agent.name}]{Style.RESET_ALL} ", end="", flush=True)
                else:
                    print(f"\n[{self.agent.name}] ", end="", flush=True)

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
                if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
                    print(f"\n\n{Fore.CYAN}再见!{Style.RESET_ALL}")
                else:
                    print("\n\n再见!")
                break
            except EOFError:
                break
            except Exception as e:
                if self.cli_config.get("color_enabled", True) and COLORS_AVAILABLE:
                    print(f"\n{Fore.RED}✗ 错误: {e}{Style.RESET_ALL}")
                    print(f"{Fore.YELLOW}提示:{Style.RESET_ALL} 如果问题持续，请检查网络连接或 API 配置")
                else:
                    print(f"\n✗ 错误: {e}")
                    print("提示: 如果问题持续，请检查网络连接或 API 配置")
                if self.agent.debug:
                    import traceback
                    traceback.print_exc()


def main():
    """主入口"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
