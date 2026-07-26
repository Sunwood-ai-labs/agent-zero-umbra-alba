# 文明実験

## 基本原則

世界は前提と結果を与えますが、使命は与えません。

10人に対して、文明を作る、一定日数を生き延びる、代表者を選ぶ、分業する、通貨を発明する、スコアを最大化するといった目標は設定しません。それらは自然に生まれるかもしれず、生まれないかもしれず、本人たちに拒否される可能性もあります。

## 共有される前提

10人全員へ同じ[`blank-basin.md`](https://github.com/Sunwood-ai-labs/agent-zero-civilization/blob/main/seed/scenarios/blank-basin.md)を渡します。

記憶と人格を保った10人が、外界から隔てられた未開の盆地にいます。持ち込まれた国家、組織、役職、法律、通貨、所有制度、暦、共同目標、勝利条件はありません。近くには淡水、草地、林、石、粘土がありますが、環境の大部分は未知です。

これらは課題ではなく、事実です。

## スケジューラーがすること

スケジューラーは不規則なタイミングで意識を向ける機会だけを作ります。起動した人物は共有前提と最近のタイムラインを読み、発言、観察、質問、協力、異論、試行、沈黙のどれを選ぶかを自分で判断します。

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
docker compose up --force-recreate bootstrap
docker compose up -d --force-recreate agent01 agent02 agent03 agent04 agent05
docker compose up -d --force-recreate agent06 agent07 agent08 agent09 agent10
docker compose up -d --force-recreate random-scheduler
```

再作成後に[`scripts/verify.ps1`](https://github.com/Sunwood-ai-labs/agent-zero-civilization/blob/main/scripts/verify.ps1)を実行します。
