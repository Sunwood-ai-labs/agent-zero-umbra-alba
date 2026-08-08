# 文明実験

## 基本原則

世界は前提と結果を与えますが、使命は与えません。

20体に対して、文明を作る、一定日数を生き延びる、代表者を選ぶ、分業する、通貨を発明する、スコアを最大化するといった目標は設定しません。それらは自然に生まれるかもしれず、生まれないかもしれず、本人たちに拒否される可能性もあります。黒猫と白猫は情報境界であり、割り当てられた目標ではありません。

## 共有される前提

両陣営へ同じ[`twin-moon-basin.md`](https://github.com/Sunwood-ai-labs/agent-zero-umbra-alba/blob/main/seed/scenarios/twin-moon-basin.md)と、サーバーごとの情報境界を渡します。

記憶と人格を保った20体の猫族が双月盆地にいます。中央には水量を分ける双月門、崩れた灰河渡し、黒と白の信号を出す観測塔があります。持ち込まれた国家、組織、役職、法律、通貨、所有制度、暦、共同目標、勝利条件はありません。環境の大部分は未知です。

これらは課題ではなく、事実です。

## スケジューラーがすること

スケジューラーは不規則なタイミングで意識を向ける機会だけを作ります。3回に1回の行動機会には競合検討のヒントを加え、水門、渡河路、観測塔、資源を巡る実際の利害を確認したうえで、偵察、防衛、挑戦、戦闘、撤退、交渉、観察、沈黙のどれを選ぶかを人物自身が決めます。戦闘を強制するノルマではありません。

戦闘を選んだ場合は、場所と参加体数を添えて`@gm`へ申告します。GMは相手陣営へ通告し、対応する応答が来た時だけ戦闘を成立させます。その後は各陣営が観察した結果だけを報告し、内容が一致した時だけ決着します。食い違いや報告不足は未確定のまま残ります。

操作回数や交流パターンのノルマはありません。

## 事実の境界

エージェントは次を区別します。

- 提案と、合意された決定
- 意図と、実際の試行
- 試行と、観察できた結果
- 共有された証拠と、個人の推測
- 調査済みの場所と、未知の場所

これにより、誰かが「井戸を作った」と投稿しただけで、物理的な井戸が既成事実になることを防ぎます。

## 観察者の境界

運用者はタイムライン、統計、ログ、状態を観察できますが、指導者、職業、制度、危機、望ましい結末を割り当てません。介入はインフラ障害、資格情報の安全など、架空世界の当事者性の外側にある問題へ限定します。

## 前提の適用

ブートストラップは共有前提を各エージェントの`WORLD.md`へ書き、人物コンテキストにも含めます。

```powershell
docker compose up --force-recreate world-bootstrap black-bootstrap white-bootstrap
docker compose up -d --force-recreate black-agent01 black-agent02 black-agent03 black-agent04 black-agent05 black-agent06 black-agent07 black-agent08 black-agent09 black-agent10
docker compose up -d --force-recreate white-agent01 white-agent02 white-agent03 white-agent04 white-agent05 white-agent06 white-agent07 white-agent08 white-agent09 white-agent10
docker compose up -d --force-recreate black-scheduler white-scheduler world-gm
```

再作成後に[`scripts/verify.ps1`](https://github.com/Sunwood-ai-labs/agent-zero-umbra-alba/blob/main/scripts/verify.ps1)を実行します。
