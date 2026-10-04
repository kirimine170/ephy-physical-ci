# Mechanical CI CLI prototype

`screen-tool` screens a nominal flat-end cylinder's entire straight axial sweep
against one frozen, hash-bound single-solid STEP obstacle. It reports
`model_clear`, `interference`, or `indeterminate` from intersection volume and
minimum distance. See [Tool screen v1](docs/tool-screen-v1.md) for its strict
schema, frozen-byte snapshot binding, synthetic oracles, and physical limits.
The existing `check-path` stage continues to use discrete pose samples.

The implemented `screen-support` stage screens nominal support/interface paths
against strict, hash-bound AABBs in `gcode_machine_coordinates` and `mm`:

```sh
physical-ci screen-support nominal.gcode --roi protected.json --output screen-001.json
```

See [Support ROI screen v1](docs/support-roi-v1.md) for the input schema,
`axis_aligned_envelope_proxy`, clip intervals, and separate `observed_hits` /
`coverage_complete` semantics. Support removal remains `not_implemented`,
physical validation remains `not_performed`, and `printer_ready` is false.

FAR向けの反復設計を想定した，小さなヘッドレス検証CLIです．凍結STEPの限定経路検査，実スライス，押出経路の抽出を機械可読な結果へまとめます．GUI操作や有料solver APIを前提にしません．

**これは物理性能の合格判定システムではありません．** FEM，サポート除去，材料校正，触覚robot連携は未実装です．出力でも各gateを`not_implemented`と明示します．

## 実装済み

- v1 manifestの単位，座標frame，剛体変換宣言，入力SHA256の検証
- 生成コードをimportせず，凍結された単一solid STEP同士を検査
- 指定した平行移動経路を一定以下の間隔でサンプリングし，体積干渉を記録
- versionを指定したローカルPrusaSlicerのCLI起動
- G-codeの直線押出経路からXYZ，線幅，層高，方向，support/interface等の役割を抽出
- 期待結果との回帰テスト，未対応G-codeや既存出力を誤って成功扱いにしない検査

合成fixtureはこの試験用に新規作成した箱・壁・張出しです．実製品のCAD，写真，プリンタ設定，生ログは含みません．

## 最小セットアップ

Python 3.10以上が必要です．実測環境はLinux / Python 3.12 / CadQuery 2.7.0 / PrusaSlicer 2.9.2です．以下はこのdirectoryで実行します．

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[geometry]'
physical-ci validate examples/synthetic/open.json
physical-ci check-path examples/synthetic/open.json --output build/open/result.json
physical-ci check-path examples/synthetic/blocked.json --output build/blocked/result.json
```

前者は`sampled_clear`，後者は`collision_found`が期待結果です．どちらも回帰テストの成功であり，後者を「設計全体が保持できる」という合格に読み替えません．

スライスとG-code解析だけなら`python -m pip install -e .`で使えます．CadQuery以外の外部実行ファイルは同梱しません．PrusaSlicerを公式配布元または信頼できるOS registryから別途用意してください．manifestのversionと一致しなければ停止します．

```sh
physical-ci slice examples/synthetic/open.json \
  --slicer prusa-slicer --output-dir build/slice-run-001 --segments

physical-ci analyze-gcode build/slice-run-001/toolpath.analysis-only.gcode \
  --output build/analysis-001.json --segments build/segments-001.jsonl
```

**同梱profileと生成G-codeは解析用です．実プリンタへ送らないでください．** 実機profileとして検証していません．このCLIにはupload・printer接続・印刷開始機能はありません．

出力は新しいpathを指定します．既存fileへの上書きや，古いG-codeの再利用は拒否します．失敗後の再試行も新しいoutput directoryを使います．

## テスト

```sh
python -m unittest discover -s tests -v
# PrusaSlicer 2.9.2を用意した場合の実CLI統合テスト
PRUSA_SLICER_TEST_BINARY=prusa-slicer python -m unittest discover -s tests -v
```

CadQuery未導入時の幾何テストと，環境変数未指定時の実PrusaSlicerテストは理由付きでskipします．skipを実測成功と数えないでください．CIではgeometry extraを導入し，合成STEPの2回帰も実行します．実slicerの統合は任意で，通常CIではadapterの異常系をmockで検査します．

fixtureを編集したときだけ次を実行し，更新されたSTEP/STLとmanifest hashを一緒にレビューします．通常テストは再生成せず，凍結fixtureを読みます．

```sh
python examples/synthetic/build_fixtures.py
```

## 終了code

- `0`: 指定stageの検査完了，または指定した期待結果と一致
- `1`: 外部backendやfile操作の失敗
- `2`: 不正入力，未対応形式，hash不一致，既存出力など
- `3`: 経路の観測結果がmanifestの期待結果と不一致

終了code `0`は物理性能，製造可能性，安全性の保証ではありません．

## 境界と文書

- [Manifest v1](docs/manifest-v1.md)
- [検証範囲と未実装gate](docs/limitations.md)
- [依存softwareとlicense](docs/dependencies.md)

この新規softwareの自作コードは，licenseをまだ選択せずsourceを公開しています．依存softwareのlicenseは変更しません．
