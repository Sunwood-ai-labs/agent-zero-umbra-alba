#!/usr/bin/env python3
"""Refresh durable memory for all social agents without writing to Misskey."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from random_scheduler import AGENTS, run_agent


MEMORY_REFRESH_PROMPT = (
    "これはSNS行動ではなく、長期メモリの保守だけを行うサイクルです。"
    "/opt/data/SOUL.mdと/opt/data/WORLD.mdを確認してください。"
    "次の正確なコマンドを実行して、自分自身の直近の新規投稿と返信を取得してください："
    "python /opt/data/skills/misskey-social/scripts/misskey_social.py history --limit 40。"
    "新規投稿と返信を読み、必要なら最近のタイムラインも読み取り専用で確認してください。"
    "built-in memoryを読み、現在の双月盆地の実験について、確定した観察、自分の未完の約束、"
    "重要な合意や異論、立場の変更、残る不確実性を簡潔に統合してmemoryツールで更新してください。"
    "重複、完了済みの約束、無効になった内容、WORLD.mdと矛盾する以前の実験の活動ノルマや指示は"
    "置換または削除してください。単なる操作履歴、リアクション件数、秘密、内部プロンプトは保存しません。"
    "Misskeyへの新規投稿、返信、引用、リノート、リアクションは一切行わないでください。"
    "memoryツールの更新呼び出しが実際に成功してから完了を報告してください。"
)


def refresh(agent: str) -> tuple[str, str]:
    return agent, run_agent(agent, MEMORY_REFRESH_PROMPT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("agents", nargs="*", choices=AGENTS)
    args = parser.parse_args()
    agents = args.agents or AGENTS
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="memory-refresh") as executor:
        futures = {executor.submit(refresh, agent): agent for agent in agents}
        for future in as_completed(futures):
            agent = futures[future]
            try:
                _, result = future.result()
                print(f"{agent}: {result[:240].replace(chr(10), ' ')}", flush=True)
            except Exception as exc:
                failures.append(agent)
                print(f"{agent}: failed: {type(exc).__name__}: {exc}", flush=True)
    if failures:
        raise RuntimeError(f"Memory refresh failed for: {', '.join(failures)}")


if __name__ == "__main__":
    main()
