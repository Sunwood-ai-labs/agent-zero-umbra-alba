# 毎時GMオートメーション

Windowsタスク `Agent Zero Umbra Alba GM Hourly` が、毎時 `gpt-5.6-luna`（推論強度 `max`）でCodexを起動します。作業ディレクトリはこのリポジトリです。監査は対象をGM台帳・直近タイムライン・直近ログに絞り、`runtime`全体の再帰走査は行いません。

## GMの役割

GMは住民の代わりに行動する人格ではありません。毎回、黒猫・白猫・世界タイムラインと`events.json`を突き合わせ、`@gm`要求が受付・通告・裁定まで届いているかを確認します。取りこぼしやインフラ障害は最小の可逆修正で直し、世界の事実を`events.json`へ手書きして確定させません。

2回連続で同じ停滞が確認された時だけ、`SOUL.md`の`## 自律の視野`に注意の向け方を最小限追加できます。人格、来歴、価値観、WORLD、メモリ、役割、勝ち筋は変更しません。変更には6時間のクールダウン、バックアップ、差分、根拠を残します。

## NyankoFace Issue

NyankoFaceのUI/API/MCPで第三者が再現できるバグ、または不足機能・繰り返し発生する操作摩擦・観測性・ドキュメント・CLI/MCPの使い勝手など、具体的な改善余地を確認した場合はIssue対象です。実際の画面/API/MCP/CLIで確認した例（または再現手順）、期待値と現状、影響、実行可能な改善案を揃え、`seed/skills/nyankoface-commons/scripts/nyankoface.py report`で秘密のない構造化報告を作り、`github-issues.py publish-report`で`Sunwood-ai-labs/NyankoFace`へ公開します。自分たちの引数ミス・設定ミス、推測、文明内の意見対立、単発の入力ミスは先にローカルで切り分け、NyankoFace側の問題として残る場合だけ報告します。公開前に既存Issueを検索して重複を避け、公開後はIssue URLと状態を確認します。公開に失敗した場合は、pending報告へ秘密のない理由を残します。トークンは`D:\Prj\.menv\github-agent-token`から読み、ログ・コミット・投稿には出しません。

## 日誌

毎回、次へ保存します。

- `runtime/guardian/reports/YYYYMMDD-HHMM.md`
- `runtime/guardian/latest.md`
- `runtime/guardian/journal/YYYY-MM-DD.md`
- `runtime/guardian/journal/latest.md`

GuardianはComposeの全32サービス、黒白両方の永続scheduler状態、boundedな`SOUL.md` 20体、空でない`WORLD.md` 20体も確認します。直近のscheduler失敗やプロバイダのクールダウンは、schedulerコンテナを再作成してDockerログが空になった直後も`unhealthy`として残します。日誌は確認済みの変化、要求への対応、実施した修正、未解決の問いを記録し、推測と確定事実を分けます。

Guardianは、コンテナ起動後120秒以内に発生した`world-gm`の接続拒否リトライを起動時の一時事象として分類します。JSONとレポートには`transientLines`として残し、継続するAPI障害やその他のエラーは従来どおり`unhealthy`と判定します。

ログ部分には、秘密をマスクしたerror/warningの短い抜粋だけを含めます。Hermesホームを再帰走査したり、Dockerログ全体をレポートへコピーしたりしません。

Codexの観測が失敗しても証拠を残せるよう、決定的なスナップショットを単独実行できます。

```powershell
.\scripts\guardian-report.ps1
.\scripts\guardian-report.ps1 -NoWrite -AsJson
.\scripts\bounded-soul.ps1 -AsJson
```

`bounded-soul.ps1 -Apply`は`runtime/guardian/reports`内の異なる2つのレポート、根拠、理由を要求します。変更前バックアップを作り、6時間のクールダウンを記録し、`## 自律の視野`の中へ箇条書きを追加する以外の変更を拒否します。人格、`WORLD.md`、メモリ、役割、勝利条件は対象外です。

## 状態確認

```powershell
Get-ScheduledTask -TaskName "Agent Zero Umbra Alba GM Hourly"
Get-ScheduledTaskInfo -TaskName "Agent Zero Umbra Alba GM Hourly"
Get-Content "$env:USERPROFILE\.codex\automations\agent-zero-umbra-alba-gm-hourly\logs\latest-run.txt"
.\scripts\gm-status.ps1 -AsJson
```

ランナーはCodex起動前に`logs/latest-run.txt`へ`status=running`を書き、終了時に最終結果へ置き換えます。途中で中断しても、前回の成功結果を今回の成功と取り違えません。ファイルロックで毎時実行の重複も安全にスキップします。タスクには45分の実行上限があるため、別のCodexランナーを起動したり、`taskkill`で終了させたりしません。最新ログを確認し、タスク境界がプロセスを解放するのを待ちます。

自動化を停止する場合は、タスクを無効化します。Docker内の`world-gm`（10秒ポーリング）による通常の場面・戦闘裁定は、毎時の神視点レビューとは独立して継続します。
