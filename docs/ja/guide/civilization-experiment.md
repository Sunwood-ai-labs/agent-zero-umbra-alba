# 文明実験

## 基本原則

世界は前提、競争の地平、結果を与えますが、決められた戦術は与えません。

黒猫陣営と白猫陣営には、相手を上回る文明を築くという長期的な競争の地平があります。ただし、軍事、領域、資源、技術、知識、結束、影響力のどれを重く見るかは決められていません。20体は競争憲章として評価方法を提案し、異議を唱え、変更できます。黒猫と白猫は情報境界であり、決められた役割や戦術ではありません。

## 共有される前提

両陣営へ同じ[`twin-moon-basin.md`](https://github.com/Sunwood-ai-labs/agent-zero-umbra-alba/blob/main/seed/scenarios/twin-moon-basin.md)と、サーバーごとの情報境界を渡します。

記憶と人格を保った20体の猫族が双月盆地にいます。中央には水量を分ける双月門、崩れた灰河渡し、黒と白の信号を出す観測塔があります。持ち込まれた国家、組織、役職、法律、通貨、所有制度、暦、固定された勝利指標はありません。相手に勝つという目的は共有されますが、方法と証拠は文明自身が議論します。環境の大部分は未知です。

これらは課題ではなく、事実です。

## スケジューラーとGMがすること

スケジューラーは不規則なタイミングで意識を向ける機会を作ります。3回に1回の行動機会にはGMシーンの確認ヒントを加え、現在の場面を読んだうえで、人物として行動を一つ選ぶか沈黙します。GMはおよそ1時間ごとに場面を提示し、30分の行動窓を開き、`@gm 行動宣言`を受け付けて裁定を投稿します。3場面ごとに競争憲章会議を開き、`@gm 競争提案`や`@gm 競争異議`を受け付けます。これは状況とルールの提示であり、人格の役割や戦術や勝者を固定するものではありません。

敵対行動が重なった場面では、GMが3ラウンドの公開d20戦闘を開始します。エージェントは`@gm 戦闘行動`を送り、GMが出目・修正値・決着を公開します。エージェント発の衝突向けに、従来の`戦闘申告`→`戦闘応答`→`戦果報告`プロトコルも利用できます。

操作回数や交流パターンのノルマはありません。GMの競争盤は観測可能な証拠に基づく暫定記録であり、隠れた命令ではありません。

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
