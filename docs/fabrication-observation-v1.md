# Fabrication observation v1

`record-fabrication`は，人手から返る造形条件，support除去，fit観察を，独立した試料・job・部品・設計revisionの期待値へ結び付ける入口です．JSONの契約とbindingを検証して観察recordを保存します．現物の寸法，嵌合性能，保持力，安全性を判定するcommandではありません．

最初の対象は[XIAOの初回fit試験](../hardware/xiao-first-fit-v0.1/README.md)から返る記録です．観察schemaは特定のカメラ，基板，ラック形状に依存しません．既存の[長さ1項目の検査](../tools/mechanical-ci/docs/length-inspection-v1.md)とその入力・出力契約は変更しません．

## 三つの独立入力

```sh
physical-ci record-fabrication SUBJECT.json \
  --part EXPECTED_PART.json \
  --observation OBSERVATION.json \
  --output RESULTS.json
```

`SUBJECT.json`は既存のsubject v1と同じで，正確に次の四つのfieldを持ちます．

- `schema_version`：整数`1`．
- `sample_id`：今回の個体を識別する文字列．同じ設計の別の造形個体には別のIDを使います．
- `design_job_ref`：設計jobの参照文字列．
- `manufacturing_job_ref`：今回の造形jobの参照文字列．

`EXPECTED_PART.json`は，観察recordとは独立に用意する部品の期待値です．fieldは正確に`schema_version`，`part_id`，`design_revision`，`artifact_sha256`です．schema versionは整数`1`，前二つの参照は文字列，SHA256は小文字の十六進数64文字です．`design_revision`は長さ要求の`requirement_revision`とは別です．

operatorは承認済みの設計recordから期待する部品，revision，artifact hashを記入します．candidate observationから同じ値をコピーするだけでは，独立した期待値になりません．このcommandは実際のCAD・STL・G-code artifactを読み込まず，hashの正しさや設計revisionとの対応も検証しません．期待値と観察側の宣言の文字列一致だけを確認し，`artifact_hash_verification`は`not_performed`です．

`OBSERVATION.json`は，正確に次のfieldを持ちます．

| Field | 内容 |
| --- | --- |
| `schema_version` | 整数`1` |
| `sample_id`，`design_job_ref`，`manufacturing_job_ref` | subjectの三つのbindingとの完全一致 |
| `part_id`，`design_revision`，`artifact_sha256` | expected partの三つのbindingとの完全一致 |
| `process_state` | operatorが明示する観察時の工程状態 |
| `source_kind` | `human_observation`または`synthetic` |
| `print_conditions` | 次節の六つの条件 |
| `support_removal` | 除去作業についての観察 |
| `fit_observation` | 指定相手への組付けについての観察 |

job refは識別子であり，設計・製造systemへ接続して内容を取得する機能ではありません．文字列は非空で，前後の空白を認めません．bindingは大文字小文字を区別して完全一致させます．case foldingや近似一致は行いません．

`process_state`は独立した文字列です．support除去やfitのstatusから自動生成しません．例えばoperatorの工程名が除去後を示し，`support_removal.status`が`not_performed`でも，このcommandはその意味的な矛盾を証明・解消しません．記録内容と現物の対応，工程名の一貫性はoperatorと呼出側が確認します．

## 造形条件と観察の形

`print_conditions`は，正確に`printer_ref`，`material_ref`，`profile_ref`，`nozzle_diameter_mm`，`layer_height_mm`，`orientation`を持ちます．すべての条件に既知／未知を明示します．

```json
{"status":"unknown","reason":"Synthetic example; condition not supplied."}
```

既知の場合は正確に`status: "known"`と`value`を持ち，未知の場合は正確に`status: "unknown"`と非空の`reason`を持ちます．両方の形を混ぜたり，省略から既定値を補ったりしません．

| 条件 | knownのvalue |
| --- | --- |
| `printer_ref`，`material_ref`，`profile_ref` | 非空の参照文字列 |
| `nozzle_diameter_mm`，`layer_height_mm` | 正の有限JSON数値．単位はfield名に示すmm |
| `orientation` | 正確に`frame`と`description`を持つobject．どちらも非空の文字列 |

数値を文字列やbooleanで代用できません．単位変換，実機profileの選択，ノズル／層高の推定，製造条件への上限・下限の推薦は行いません．入力数値の表現と資源制限は共通JSON readerの範囲に従います．`orientation`は申告したframeと向きの説明であり，CAD座標変換や実際の配置を検証した結果ではありません．profile refも実機で使った設定の証明にはなりません．既存`slice`のanalysis-only profile・G-codeを，実印刷条件の証拠へ自動昇格しません．

`support_removal`は正確に`status`と`description`を持ちます．statusは`removed`，`partial`，`not_performed`，`unknown`のいずれかです．非空のdescriptionへ観察した作業・残存状態を記録します．`removed`はoperatorによる観察の宣言で，ソフトウェアによる除去完了の確認ではありません．除去力や工具力は推定しません．

`fit_observation`は正確に`status`，`target_ref`，`description`を持ちます．statusは`assembled`，`interference`，`not_tested`，`unknown`のいずれかです．`target_ref`は同じ既知／未知の形を使い，knownのvalueは非空の相手参照文字列です．`assembled`または`interference`にはknownの`target_ref`が必要です．descriptionも非空です．`assembled`から寸法適合，所要保持力，反転・移動時の保持，電気・熱の安全性を導きません．定性的なfit観察を`human_measurement`として扱いません．

## 完全syntheticの入力例

以下を同じ作業directoryへUTF-8で保存します．参照ID，revision，ゼロを64個並べたartifact hash，工程名，descriptionはすべてこのschema例のための架空データです．実artifactのhash，プリンタ設定，現物観察，測定結果を示しません．造形条件はすべてunknownとします．

`subject.json`：

```json
{
  "schema_version": 1,
  "sample_id": "synthetic-coupon-001",
  "design_job_ref": "synthetic-design-001",
  "manufacturing_job_ref": "synthetic-print-001"
}
```

`expected-part.json`：

```json
{
  "schema_version": 1,
  "part_id": "synthetic-coupon",
  "design_revision": "synthetic-r1",
  "artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

`observation.json`：

```json
{
  "schema_version": 1,
  "sample_id": "synthetic-coupon-001",
  "design_job_ref": "synthetic-design-001",
  "manufacturing_job_ref": "synthetic-print-001",
  "part_id": "synthetic-coupon",
  "design_revision": "synthetic-r1",
  "artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "process_state": "synthetic_as_printed",
  "source_kind": "synthetic",
  "print_conditions": {
    "printer_ref": {
      "status": "unknown",
      "reason": "Synthetic example; printer not supplied."
    },
    "material_ref": {
      "status": "unknown",
      "reason": "Synthetic example; material not supplied."
    },
    "profile_ref": {
      "status": "unknown",
      "reason": "Synthetic example; profile not supplied."
    },
    "nozzle_diameter_mm": {
      "status": "unknown",
      "reason": "Synthetic example; nozzle not supplied."
    },
    "layer_height_mm": {
      "status": "unknown",
      "reason": "Synthetic example; layer height not supplied."
    },
    "orientation": {
      "status": "unknown",
      "reason": "Synthetic example; orientation not supplied."
    }
  },
  "support_removal": {
    "status": "not_performed",
    "description": "Synthetic example; no support-removal operation occurred."
  },
  "fit_observation": {
    "status": "not_tested",
    "target_ref": {
      "status": "unknown",
      "reason": "Synthetic example; mating target not supplied."
    },
    "description": "Synthetic example; no physical fit test occurred."
  }
}
```

既存CLIを使える環境で，この作業directoryから実行します．

```sh
physical-ci record-fabrication subject.json \
  --part expected-part.json \
  --observation observation.json \
  --output results/fabrication-001.json
```

出力は入力と異なる新規pathを指定します．再実行には例えば`results/fabrication-002.json`を使い，既存出力を上書きしません．この例の検証完了は架空recordの契約成立を示します．印刷・現物fit成功の試験ではありません．

## reportと終了code

reportの`input_hashes`は，実際に解析した三つの入力bytesのSHA256を`subject_sha256`，`part_sha256`，`observation_sha256`へ記録します．JSONの空白や改行を変えるとhashも変わります．part内の申告artifact hashを実ファイルへ照合したという意味ではありません．

正常終了reportの境界は次のとおりです．

```json
{
  "execution_status": "complete",
  "judgment": "not_applicable",
  "artifact_hash_verification": "not_performed",
  "physical_validation": "not_performed",
  "printer_ready": false
}
```

これはreportの抜粋です．`complete`はrecordの構造とbindingの検証完了で，物理的な合格ではありません．unknown条件や未試験の観察を，既知条件や成功結果へ置換しません．`evidence_class`はhuman observationなら`observation`，syntheticなら`record`です．どちらも`measurement`へ昇格しません．report内の既知のmm数値は精度を保つためdecimal文字列として保存しますが，入力側にはJSON数値が必要です．

各JSONは64 KiBまでのregular fileです．unknown／missing field，nested objectの余分なfield，duplicate key，不正UTF-8，不正JSON，NaN／infinity，boolean数値，schema versionやbindingの不一致を拒否します．入力・証跡を実行せず，ネットワークや機器へ送信しません．

| 状況 | 終了code | 意味 |
| --- | --- | --- |
| record検証完了 | `0` | 観察recordを保存した．fit合格を意味しない |
| file I/O等の実行error | `1` | 検証を完了できない |
| 不正入力，binding不一致，既存出力，不正CLI引数 | `2` | 契約または出力条件を満たさない |

不正入力やbinding不一致では結果fileを生成しません．既存出力や入力への上書きを拒否し，結果fileはexclusive creationで作ります．結果書込中のfile I/O errorでは未完了fileが残る場合があります．このfileを成功結果として再利用せず，再試行にも新規pathを使います．`record-fabrication`はunknown optionと省略したflagを受け付けません．CLI引数の解析errorと，読込後の入力errorは区別してください．hashはbytesの対応を示し，operatorの観察内容，試料との対応，測定の真正性を証明しません．

## 長さ検査への結合

観察JSONをsidecarとして先に固定し，そのraw bytesのSHA256を測定recordの`evidence_refs`へ入れます．例えばsidecarと測定JSONが同じdirectoryなら，referenceは次の形です．

```json
{"path":"observation.json","sha256":"<SHA256 of the exact observation.json bytes>"}
```

この抜粋のhashは記入位置を示すplaceholderであり，有効な入力ではありません．既存長さ検査の相対POSIX path，regular file，容量，SHA256検証をそのまま適用します．raw sidecarを参照し，fabrication reportのhashを代用しません．測定後にsidecarを編集した場合は，新しいrecordとして再検証し，参照hashも更新します．古い検査結果を新しい条件へ付け替えません．

長さの実測がある場合だけ，独立に承認された要求と測定recordを用意して別commandを実行します．以下の二つのJSONは利用者が別途用意する入力で，本例では測定値，公差，不確かさを作りません．

```sh
physical-ci inspect-length subject.json \
  --requirement approved-length-requirement.json \
  --measurement human-length-measurement.json \
  --output results/length-001.json
```

結合する呼出側は，二つのreportの`input_hashes.subject_sha256`が同じことと，fabrication reportの`input_hashes.observation_sha256`が長さreportの`verified_evidence_sha256`に含まれることを確認します．検査error時や証跡欠落時には，結合成功として扱いません．fabrication側のexpected part入力と，承認済み設計recordとの対応も保持します．

既存`inspect-length`はsidecarの意味を解析せず，造形条件やfitのstatus，部品revisionを新たに判定しません．長さ要求と測定recordの`process_state`は既存契約どおり完全一致を検査しますが，観察sidecarの`process_state`との一致は自動強制しません．呼出側が，両recordの工程状態を明示的に比較し，異なる工程の記録を同じ現物状態の証拠として扱わないようにします．矛盾したoperator申告をhash一致で正しいと認定できません．

## 次の現物入力

実試料へ使うときは，試料IDと設計／製造job，承認済み部品ID・設計revision・期待artifact hashを先に用意します．operatorは実際のprinter，material，profile，ノズル径，層高，造形姿勢とそのframe，support除去の状態と作業内容，fitの相手と観察内容を確認します．不足する項目はunknownの理由を保持し，推定で補いません．この入口だけで全条件が揃ったことを保証しません．

数値寸法を検査するには，別途，承認された長さ要求revision，測定method，工程状態，明示的な公差・不確かさpolicy，実測recordと試料に対応する証跡が必要です．fit観察から値や公差を生成せず，製造／観察recordと数値測定recordを分けて残します．FEM，camera計測，保持力評価，robot操作，印刷開始，ephyへの自動feedback適用はこのcommandの範囲に含みません．
