"""
LightHermes 命令行界面

提供交互式对话界面
"""

import sys
import os
import yaml
from pathlib import Path

from lighthermes.core import LightHermes


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

        print("╭─────────────────────────────────────╮")
        print("│  LightHermes v0.2.0                │")
        print("│  轻量级自进化智能体框架              │")
        print("╰─────────────────────────────────────╯")
        print()

    def print_help(self):
        """打印帮助信息"""
        print("\n可用命令:")
        print("  /help       - 显示帮助信息")
        print("  /skills     - 列出所有可用技能")
        print("  /memory     - 显示记忆系统统计")
        print("  /config     - 显示当前配置")
        print("  /clear      - 清屏")
        print("  /exit       - 退出")
        print()

    def show_skills(self):
        """显示所有技能"""
        skills = self.agent.skill_loader.get_all_skills()
        if not skills:
            print("\n暂无可用技能")
            return

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
        elif cmd == "/clear":
            self.clear_screen()
        elif cmd == "/exit":
            return False
        else:
            print(f"未知命令: {cmd}")
            print("输入 /help 查看可用命令")
        return True

    def run(self):
        """运行交互式 CLI"""
        try:
            self.init_agent()
        except Exception as e:
            print(f"初始化失败: {e}")
            print("\n请检查:")
            print("1. config.yaml 文件是否存在")
            print("2. OPENAI_API_KEY 环境变量是否设置")
            return

        self.print_banner()

        prompt_symbol = self.cli_config.get("prompt_symbol", ">")
        stream_output = self.cli_config.get("stream_output", True)

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
                print("\n\n再见!")
                break
            except EOFError:
                break
            except Exception as e:
                print(f"\n错误: {e}")
                if self.agent.debug:
                    import traceback
                    traceback.print_exc()


def main():
    """主入口"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
