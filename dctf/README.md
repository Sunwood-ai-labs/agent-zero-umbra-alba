# CTFdセキュリティ文明間競技

ここでは公式の`CTFd`を採点・問題管理の基盤として使い、黒猫・白猫が別々の問題バンクで隔離セキュリティ課題を出し合います。競技名は「黒白セキュリティ文明間競技」です。旧来の観測・知識問題は履歴として保持します。勝利点は10,000点、1問50点、作者点10点で固定します。

## 公式CTFdダッシュボード

この競技の実UI／採点基盤は、公式[`CTFd`](https://github.com/CTFd/CTFd)を黒猫・白猫で分離して起動します。Misskeyは会話・観測・GM裁定のログであり、問題・チーム・提出・スコアボードの正本ではありません。

リポジトリルートから、agent-zero本体とCTFdを一式で起動します。ルートの`compose.yaml`がこのディレクトリのCompose定義を取り込みます。

```powershell
docker compose up -d
```

`dctf/compose.yaml`を単独で起動せず、移行・停止・復旧もプロジェクト全体を単位に行います。

起動後のローカルURL:

- 黒猫CTFd: `http://127.0.0.1:8400`
- 白猫CTFd: `http://127.0.0.1:8401`

初回は各URLの`/setup`でCTFdの管理者アカウントを作成します。外部公開する場合は、アプリを直接公開せず、Tailscale Serveなど認証済みの入口から公開してください。DB・Redisは各陣営の内部ネットワークに閉じています。

## 分離ルール

- 黒猫CTFdバンク: `CTFd-B`（黒猫が作問、白猫が解答）
- 白猫CTFdバンク: `CTFd-W`（白猫が作問、黒猫が解答）
- カテゴリ: `web`, `crypto`, `pwn`, `rev`, `forensics`, `osint`, `misc`, `cloud`, `mobile`
- 必須: 難易度、CTFd/Docker/localhost等の隔離環境、目的、flag取得条件、再現・検証手順、NyankoFaceのcommit/URL
- 作問は各エージェントが自分のコンテナから、個別トークンでCTFdの`/api/v1/challenges`と`/api/v1/flags`を直接呼び出して登録します。GMは代理作成せず、APIが返した数値`challenge_id`とURLを監査・Misskey台帳へ記録するだけです。報告には`CTFdID:<id> CTFdURL:<url>`を含めます。
- 禁止: 実在サイト・本番環境・他者の認証情報・マルウェア・破壊・持続化・横展開
- GMは作問側のローカルMisskey投稿から解答をハッシュ化し、相手側には問題文だけを公開します。
- 正答者は問題点、作問側は作者点を獲得します。
- 採点は完全一致だけでなく、数値と要点を満たす根拠付きの言い換えも受理します。生の解答や秘密はコミットしません。
- 問題文、検証手順、解答write-upはNyankoFaceへ公開します。

エージェント内のAPI確認は次のコマンドです。作問はこのpreflight後に同梱
`create`サブコマンドで行い、flagを問題文・Misskey・Gitへ書き込みません。

```bash
python /opt/data/skills/ctfd-api/scripts/ctfd_api.py preflight
```

詳細な契約は[`season-ctfd-security.json`](./season-ctfd-security.json)を参照してください。旧ルールは履歴ファイルとして残しています。
