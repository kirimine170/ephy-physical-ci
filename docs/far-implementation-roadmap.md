# Full Automate Robotics 実装ロードマップ

調査日：2026-10-08．本書は実装計画であり，無人製造設備の完成報告ではありません．最初の到達点は，共通モジュールラックの嵌合クーポンについて **CAD設計 → 幾何・製造指令の検査 → 人が監督する印刷 → 人手実測 → ephy向け改善入力 → 次の設計** を一往復させることです．ロボットによる取り外し・搬送・触覚検査は，この往復を再現できてから追加します．期限や進捗率ではなく，成果物と受入条件で段階を進めます．

## 1．確認した既存実装

`ephy-physical-ci` の調査基点は [commit 3cfb09f](https://github.com/kirimine170/ephy-physical-ci/tree/3cfb09f1f8abce96d54a7b1f6647ec58823ba738)，`ephy-cam` は [commit 11e81ef](https://github.com/kirimine170/ephy-cam/tree/11e81efae9049e3c4c0d40a4eb3b8cc926d92c60)です．以下はREADMEだけでなく，対象のsourceと契約文書を照合した状態です．

| 既存の成果物 | 実装済みの能力 | 今回の計画で補うもの |
| --- | --- | --- |
| [Mechanical CLI](../tools/mechanical-ci/README.md) の `validate` / `check-path` | mm・座標frame・入力hashを確認し，凍結単一solid STEPの指定平行移動を離散姿勢で検査 | 一般的な回転・6自由度の連続経路保証，製品の保持力 |
| [Tool screen](../tools/mechanical-ci/docs/tool-screen-v1.md) | 公称平底円筒工具の指定直進軸方向sweepを，一つの凍結STEP障害物へ照合 | 柄を含む任意工具，横移動・回転，実工具アクセス，除去力 |
| [Support screen](../tools/mechanical-ci/docs/support-roi-v1.md) と `slice` / `analyze-gcode` | 固定版ローカルPrusaSlicer，入力snapshotのhash結合，対応する直線押出指令の抽出，support/interface経路とAABB proxyの照合 | 実プリンタprofileの承認，造形品質，ヘッド全体の衝突，サポート除去 |
| [Measured length inspection v1](../tools/mechanical-ci/docs/length-inspection-v1.md) | 一試料・一寸法の人手JSONを独立した要求revisionへ照合し，明示した不確かさ方針で `pass/fail/indeterminate` を返す | 測定器接続，多寸法集約，画像による寸法生成，製品全体の合否 |
| [ephy-cam offline capture](https://github.com/kirimine170/ephy-cam/blob/11e81efae9049e3c4c0d40a4eb3b8cc926d92c60/docs/inspection-capture-v1.md) | 独立sessionと既存captureのsnapshotをhashで結合し，read-only再生と `evidence_refs` を生成 | 校正評価，寸法・不確かさの算出，Physical CI台帳・Karteへの接続 |
| [Mechanical experiments](../experiments/mechanical-ci/README.md) | 合成STEPの限定探索，線形FEM，保存slice証跡等の個別再現実験 | 統合pipelineと現物検証 |
| [XIAO holders](../hardware/xiao-first-fit-v0.1/README.md) | オリジナルの無通電fit確認用ホルダー・共通フット・トレーとデジタル検証 | 汎用ラックの寸法契約，現物fit・荷重・熱・通電確認 |

`inspect-length` は人手の測定記録を `evidence_class=measurement` と扱えますが，software自身は測定していないため `physical_validation=not_performed` と `printer_ready=false` を維持します．exit 0でも `fail`，`indeterminate`，入力不足による `not_run` があり，結果JSONを読む必要があります．

ephy-camのbundleは常に `metrology_eligible=false`，`physical_validation=not_performed`，`adopted=false` です．試料の同一性は `operator_assertion` であり，画像hashは現物の同一性を証明しません．校正の申告だけでは計測へ昇格しません．再生はJPEG decodeを行わず，旧XIAO referenceの時刻はJPEG受信後のhost保存時刻で，露光時刻は不明です．

既存の広い境界文書には連続衝突が未実装とありますが，`screen-tool` の限定した円筒軸方向sweepは実装済みです．一般的な連続6自由度検査とは分けます．本書は既存CLIのschemaや状態flagを変更しません．

## 2．共通1U/2U風モジュールラックを最初の対象にする

提案する対象は，交換式moduleを共通frameへ載せるラックです．カメラ，MCU，計測器，照明，電源の各adapterを同じ取付契約へ接続します．カメラ専用の棚をrack全体の基準にしません．最初は無通電のframe・rail・adapter couponだけでfitを確かめます．

`U_pitch_mm` を高さの共通増分とし，1U moduleは一段，2U moduleは連続する二段を占有する構成を提案します．数値，幅，奥行き，穴列，荷重は物理入力を得てから独立要求として凍結します．これは内部のmodular interface案で，19-inch rack等への規格適合・互換性をまだ主張しません．

| 共通interfaceで固定するもの | 初期に検査するもの |
| --- | --- |
| rack座標原点，基準面，挿入方向，`U_pitch_mm`，幅・奥行きenvelope | adapterの位置再現性，1U/2Uの占有と隣接moduleとの干渉 |
| rail/穴/ねじ/着座面の寸法とrevision，公差，組立方法 | rail幅，穴位置，着座深さの実測，実ねじ・工具の到達性 |
| moduleの質量・重心・支持位置，ケーブルの抜差し空間 | たわみ，保持，転倒，ケーブル引張の試験条件 |
| ケーブル経路，交換手順，放熱・照明・視野のenvelope | 実コネクタと照明の干渉，通電前の熱・電気条件 |
| 製造・検査のdatumと試料ID表示位置 | CAD→print→fixture→camera座標変換と試料の取り違え防止 |

既存XIAOの36 mm共通フットはadapter候補です．ラックの新しいrail規格や保持力の根拠には転用しません．フットの実測と，adapterの着座・脱落・熱条件を別に検証します．最初のCAD成果物は共通interfaceのcoupon，1U carrier，2U carrierの順とし，小さいcouponで公差を決めてからframe全体を印刷します．

カメラadapterは実際のboard・camera module・lens・ケーブルの型番とrevisionを確認して設計します．[Seeedのofficial guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)はOV2640から後続OV3660への変更とOV5640互換を説明しています．同じXIAO名やsoftware例の互換性から機械的な外形・lens位置・ケーブル条件の一致を推定しません．flexの曲げ半径や許容力はmanufacturer資料または現物試験を得てから決めます．

## 3．証拠を分けるarchitecture

以下は将来の接続案です．現在のrepositoryにproduction scheduler，printer adapter，feedback writerはありません．

```mermaid
flowchart LR
  R["独立要求・revision"] --> D["CAD候補・凍結STEP/STL"]
  D --> G["幾何の検査"]
  D --> S["slice・toolpath検査"]
  G --> P["承認済み実機profileで印刷"]
  S --> P
  P --> H["後処理・試料識別"]
  H --> M["人手実測と不確かさ"]
  H --> O["カメラ観察bundle"]
  R --> J["要求との比較"]
  M --> J
  O --> E["証跡参照"]
  E --> J
  J --> F["ephy向け改善入力"]
  F --> D
  D --> A["FEM予測・仮定"]
```

カメラ観察から比較判定へ渡すのは証跡参照です．画像から寸法を生成するには別の校正済み計測adapterが必要です．FEM結果も `prediction` として別に保存します．

| 層 | 保持する情報・状態 | この層だけでは分からないこと |
| --- | --- | --- |
| geometry | solid数，validity，寸法，干渉，経路の検査範囲，近似・未対応事項 | 実印刷の接着，変形，摩擦，保持力 |
| slice/toolpath | slicer版，profile/mesh/G-code hash，層と押出線，role，座標変換，coverage | 実際の吐出量，head clearance，造形・除去成功 |
| FEM | mesh，材料，配向，荷重・支持・接触の仮定，収束，感度，予測値 | 校正なしの実部品強度・破断・creep |
| observation | session，撮影条件，試料の申告，画像・metadataのhash | 寸法，力，不確かさ，試料の真正性 |
| measurement | 実測値，単位，method，process state，器具・校正，生値，不確かさの根拠 | 未測定featureや設計全体の合格 |
| decision / feedback | 独立要求revision，対象feature，判断理由，次候補の変更範囲 | 印刷・robot操作の自動許可 |

接続時の共通キーは `sample_id`，`design_job_ref`，`manufacturing_job_ref`，要求revisionとhashです．CAD，parameter，STL，profile，G-code，fixture，計測器，softwareの版も対応付けます．ephy-camの `session_id/task_id` と上記job参照は，独立したcallerがmappingを宣言し，候補JSONから自動的に正解を作らない構成にします．

既存 `inspect-length` は未知fieldを拒否します．rack全体のmanifest，器具の生値，FEM，printer状態は**別sidecar**へ置き，現行v1へ任意fieldを足しません．bundleを測定JSONの隣で参照する接続も，bundle生成・再生と人手測定を独立に行います．実画像・host ID・計測log・verification bundleはGit外に置き，公開Gitにはoriginal source・文書・合成fixtureだけを置きます．

将来のrunnerは `execution_status` と `judgment` を別に集約します．unknown，未対応，欠測，skip，hash/revision不一致をpassへ変換せず，stageごとの理由を残します．`inspect-length` の三状態と他commandの既存enumをadapterで保持し，万能な `all_pass` flagで印刷を許可しません．

## 4．API/CLI候補の比較と採用順

ローカル実行のsoftwareを優先し，反復ごとのsolver/API課金を必須にしません．無料softwareでも計算資源，電力，材料，測定器，printer/robotの費用は別です．依存licenseとこのrepositoryのlicense未選定状態は別に管理します．調査日のofficial docsを示し，実装時には実行binary・library・kernelの版とhashを固定します．

| 領域・候補 | headlessの入口と一次資料 | 採用判断・制限 |
| --- | --- | --- |
| CadQuery | Python library，[official introduction](https://cadquery.readthedocs.io/en/latest/intro.html)，[v2.7.0 shape source](https://github.com/CadQuery/cadquery/blob/v2.7.0/cadquery/occ_impl/shapes.py) | 第一候補．既存geometry extraは2.7.0．`isValid()` はOCCT `BRepCheck_Analyzer` を利用．生成と検査が同じkernelの場合，別kernelの独立性は主張しない |
| build123d | Python，[official documentation](https://build123d.readthedocs.io/en/latest/) | parametric CAD候補．既存CadQueryからの移行は必須にしない．`latest` の開発版APIを固定版へ混ぜない |
| FreeCAD / OpenSCAD | [FreeCAD official source](https://github.com/FreeCAD/FreeCAD)と[既存のheadless macro](../hardware/xiao-first-fit-v0.1/sources/build_physicalci.FCMacro)，[OpenSCAD CLI manual](https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Using_OpenSCAD_in_a_command_line_environment) | FreeCADは既存XIAO macroの再生成候補．GUI文書をレビューしつつlibrary実行を固定環境で使う．OpenSCADはCSG/STL couponには有用だが，STEP/BRep検査との対応を別に用意する |
| PrusaSlicer | CLI，[official CLI wiki](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface)，[2.9.2 action source](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/CLI/ProcessActions.cpp) | 第一候補．既存検証版2.9.2とadapterを維持．新しいprofile/版は独立の互換testを追加する．正常終了だけを製造合格にしない |
| Moonraker / Klipper | HTTP/JSON-RPC，[printer API](https://moonraker.readthedocs.io/en/stable/external_api/printer/) と [file API](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/#file-upload) | 対応実機がある場合の候補．upload，start，状態照会，pause/cancelを分離．API応答と現物完了は別 |
| OctoPrint | REST，[file API](https://docs.octoprint.org/en/main/api/files.html)，[job API](https://docs.octoprint.org/en/main/api/job.html) | 既存controllerに合う場合の代案．API keyはGit外．二つのprinter backendを同時に作らず，実機に合う一つを選ぶ |
| Gmsh + CalculiX | [Gmsh batch/Python API](https://gmsh.info/doc/texinfo/#Gmsh-command_002dline-interface)，[CalculiX official distribution](https://www.dhondt.de/) / [capabilities](https://www.dhondt.de/ov_calcu.htm) | FEM比較を後段で追加．mesh generatorとsolverを分離できる．メッシュと材料仮定の校正が先 |
| OpenCV | Python/C++，[calibration](https://docs.opencv.org/4.13.0/dc/dbb/tutorial_py_calibration.html)，[ArUco detection/pose](https://docs.opencv.org/4.13.0/d5/dae/tutorial_aruco_detection.html) | camera→mm計測adapterの候補．画像fileから数値出力し，表示windowを省けばheadless化できる．一般3D寸法は初期対象にしない |
| Open3D | Python，[ICP registration](https://www.open3d.org/docs/release/tutorial/pipelines/icp_registration.html) | depth/scan実機を得た後の候補．登録のfitness/RMSEだけで寸法合格にしない |
| DIGIT / TACTO / GelSight | [DIGIT paper](https://arxiv.org/abs/2005.14679)，[interface](https://github.com/facebookresearch/digit-interface)，[design](https://github.com/facebookresearch/digit-design)，[TACTO](https://github.com/facebookresearch/tacto)，[GelSight SDK/FAQ](https://github.com/gelsightinc/gsrobotics) | 将来の接触確認・滑り・挿入補助．DIGITの設計/interfaceはCC-BY-NCでarchive済み．TACTOはMITだが現物接触の校正を代替しない．GelSight SDKはGPL-3.0，sensor hardwareは別途必要 |

CadQueryのSTL exportはtessellationのtolerance・角度・相対/絶対指定も固定します．STEPのmm契約，CAD姿勢からprint姿勢への剛体変換，slicerのauto-placement/scaleの扱いを保存します．最新版だけに存在するunit APIを2.7.0の例へ持ち込まず，bounding boxと既知寸法で倍率を照合します．

主要licenseは[CadQueryのApache-2.0](https://github.com/CadQuery/cadquery/blob/v2.7.0/LICENSE)，[OCCTのLGPL-2.1と例外](https://occt3d.com/dev/doc/overview/html/occt_public_license.html)，[PrusaSlicerのAGPL-3.0](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/LICENSE)，[MoonrakerのGPL-3.0](https://github.com/Arksine/moonraker/blob/master/LICENSE)，[OctoPrintのAGPL-3.0](https://github.com/OctoPrint/OctoPrint/blob/main/LICENSE.txt)です．ローカル・自己hostの呼出しが可能であることと，再配布条件は分けて確認します．

PrusaSlicer 2.9.2のsourceには，printが空またはvolume外の場合に `Nothing to print` を出して処理が成功returnする経路があります．したがって終了codeに加え，新規で非空のG-code，層と正の押出，対象featureの領域，入力hashと期待するprofile/版を確認する必要があります．既存CLIは解析専用profileとG-codeを使い，upload・print startを実装していません．

## 5．最小milestoneと受入条件

以下は追加実装の提案です．公差，荷重，寸法，不確かさ上限はこの文書が決める製品仕様ではありません．各段階を始める前に，独立した要求revisionへ明記します．

| 段階 | 最小成果物 | 受入条件 | 進行を止める入力不足 |
| --- | --- | --- | --- |
| M0：証跡を一つの試料へ結合 | 合成session→bundle replay→独立した合成測定JSON（`source_kind=synthetic`）→`inspect-length` のread-only統合fixture | pass/fail/indeterminateを再現．別sample/job/revisionや改ざんhashはerror，欠測は`not_run/indeterminate`として再現し，passへ昇格しない．既存flagを保つ | 対応付けるID・要求・証跡の選択方法 |
| M1：共通rack interface | 単位・datum・1U/2U envelopeを持つ要求と，original parametric coupon | rail/穴/着座面のfeature IDを固定．STEP再読込，solid数，validity，寸法，STL倍率を照合．frameと異なるmodule adapterで同じ契約をレビュー | rackの寸法，printer envelope，締結，荷重，測定datum |
| M2：製造指令の検査 | 固定profileのslice，対象couponのfeature/ROIとtoolpath report | 生成物のfreshness/hash，対応G-codeのcoverage，実印刷範囲，壁・穴・bridge/support/brimを評価．unknown roleや座標未確定をpassにしない | 実プリンタ・ノズル・材料・profile，CAD→machine変換 |
| M3：監督付き印刷・後処理 | 一つのcouponのprint jobと試料ID，後処理記録 | 実機profileと送信G-code hashを照合．印刷終了と試料回収を確認．support除去前後を区別し，失敗と中断を保存 | 実機操作の許可，状態取得，bed冷却・取り外し手順 |
| M4：実測feedbackの一往復 | 同じinterfaceの実測，要求比較，次候補parameter差分，再印刷の比較 | 独立要求を変更せず測定．変更parameterと根拠，旧新revision，同じmethod/process stateを対応付ける．改善しなかった結果も保存 | 計測器，校正/不確かさ，公差，実試料 |
| M5：camera計測の追加 | 同一検査平面の一寸法に限定したOpenCV adapter | 独立既知長ゲージと人手値で視野内の誤差・bias・反復性・不確かさを確認．判定不能画像を拒否．ephy-cam観察bundleとは別出力 | camera/レンズ/焦点/解像度，距離，照明，治具，独立基準 |
| M6：校正したFEM比較 | rack frame一荷重caseのmesh/solver deckと変位予測，現物比較 | mesh収束，荷重・反力/モーメント釣合い，支持/材料/接触感度を評価．実物との差を別に記録 | 実荷重・支持・締結，材料定数，配向，力–変位試験 |
| M7：robot/触覚による一操作 | 一coupon・一fixtureの保持→搬送→配置，後に取り外し/挿入 | 接触力/速度/可動範囲/停止を独立に制限し，落下・誤配置・過大接触・通信断を確認．失敗時は自動再開しない | robot/把持器/sensor，校正，作業域，力上限，停止系 |

依存順はM0→M1/M2→M3→M4です．M5とM6はM4後の別枝として追加でき，FEMの導入を最初の寸法feedbackの必須条件にはしません．M7は機械・計測・停止の条件が揃ったときに限定操作から始めます．

### 最初の実測pilot

共通interfaceに効くrail幅，穴位置，着座深さから少なくとも一寸法を選び，現行CLIの一寸法契約で比較します．反復性を見るpilot案は同条件の試作品3個，対象寸法を取り外し・置き直して各5回です．この個数は着手用の提案で，量産qualificationや統計的な信頼性保証ではありません．生値，datum，計測器・校正ID，method，温度等の条件をGit外に保存し，器具の分解能をそのまま不確かさへ代入しません．

初期判定は既存 `interval_containment_v1` を候補とします．供給された非負半幅 `u` に対し，`[x-u,x+u]` が独立公差 `[L,H]` 内ならpass，厳密に離れていればfail，境界と重なる場合や不確かさ未評価ならindeterminateです．これはprojectの数学的なdecision policyで，softwareがcoverage factorや確率を導いたものではありません．[NIST TN 1297](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-6-expanded-uncertainty) の拡張不確かさを採用する場合は，評価方法・coverage factor・対象条件を別に明記します．

画像計測の最初の構成は，固定した単一camera，拡散照明，寸法基準と対象が同一planeにある繰り返し設置可能なfixtureを提案します．校正に使っていない既知長ゲージを対象寸法範囲と複数の視野位置で測り，人手値と比較し，置き直し・照明変化への感度を評価してから使います．再投影誤差の小ささをmm精度と読み替えません．同一planeでない高さ差，遮蔽，輪郭不明，lens/焦点変更は再評価対象です．点群段階ではdatumから剛体姿勢を合わせ，scaleを自由にfitして寸法誤差を消さず，ROIごとの寸法・残差・欠測を報告します．

## 6．FEM・支持材・触覚を現物に接続する条件

FEMはsolverが正常終了したことと物性モデルが妥当なことを分けます．最初は単純梁の解析解との照合とmesh refinementを通し，その後ラック一荷重caseへ進みます．ねじ面を完全固定した条件，等方PLA，infillの均質化，摩擦係数，接触・大変形の省略は仮定として残します．材料は実際の印刷方向とprofileのcouponで校正し，変位の収束を特異点の最大応力や破壊荷重の収束へ読み替えません．保持力，creep，fatigueは別の試験です．既存[frame compliance](../experiments/mechanical-ci/frame-compliance/README.md)と[lessons](../experiments/mechanical-ci/lessons.md)はこの区別の出発点になります．

support経路が0でもbridge成立は分かりません．supportが出ても工具が届くこと，壊さず除去できること，除去後に嵌合することは分かりません．同じcoupon・profileでsupport/bridge設定を変え，層と指令経路を確認した後，実物の除去前後を観察・測定します．工具sweepの限定結果に加え，実工具の柄，接近姿勢，退避，破片，作業力を別に扱います．

DIGIT論文は小物の実接触操作を報告していますが，ラックの取り外し・嵌合の実証ではありません．TACTOのofficial READMEは変形・摩擦の物理的正確さを保証しないと明記します．GelSightのofficial FAQもMiniをmetrology deviceとせず，再構成のsystem accuracyを提示していません．力の推定には画像/変位から別の校正モデルが必要です．初期用途は接触・滑り・配置の観察とし，寸法や接触力の合格判定には独立基準を使います．

[Brion & Pattinson，Nature Communications 13，4654（2022）](https://www.repository.cam.ac.uk/items/510138b4-f4c4-4da5-b449-2a4eee505565)は，画像と制御loopで実機の押出異常を検出・補正した研究です．[著者コードCAXTON](https://github.com/cam-cambridge/caxton)はMITで，流量・横速度・Z offset・hotend温度の分類を扱います．これは実機工程補正の研究結果です．完成品の公差，荷重，汎用ラックの無人製造を保証せず，本書のM4で提案する「測定値から次のCADを改善するloop」の実装済み根拠にもなりません．本調査ではモデルを実行・学習していません．

## 7．ephyへ戻す最小feedback契約

以下は未実装のsidecar案で，Karteやworkerへ書き込む既存APIを意味しません．M4ではまずprivate fileを読み取り，レビュー可能な次候補差分を作るところまでを一単位にします．

| 項目 | 意味 |
| --- | --- |
| 対象 | 試料/job，design・requirement revision，feature，CAD/parameter/profile/G-codeのhash |
| 根拠 | geometry/toolpathの各result，観察bundle参照，人手実測result，FEM予測と仮定を別欄に保持 |
| 判定 | execution status，既存judgment，reason，欠測・不確かさ，対象process state |
| 変更案 | parameter名，旧値/新値，単位，許可範囲，変更理由，予測する効果 |
| 実験計画 | 固定条件，次試料ID，測定method，成功/失敗の判定規則，停止条件 |
| 対比較 | 前試料との差，改善なし・副作用・未観測feature，採用の明示decision |

最初は一つのparameterを限られた範囲で変える決定的な探索やgrid比較で十分です．CAD公称値と実測値の差を原因未分離のまま補正係数にせず，印刷倍率，姿勢，収縮，後処理，datum，測定biasを点検します．公差の緩和は製品要求の別revisionとして扱い，候補を通すための自動修正は行いません．改善判断と実機操作の許可を分離します．

将来printer APIを追加する際は，job ID，対象file hash，controller/firmwareの版，状態遷移を記録します．upload成功，start受付，printer完了，回収，後処理，検査完了を別状態にします．timeoutや通信断後は実機状態を照会し，送信結果が不明なstartを無条件で再送しません．同じresourceを二jobが動かさないlockと，独立停止手順が必要です．これは将来adapterの受入条件で，現行CLIへネットワーク接続を追加する変更ではありません．

## 8．未入力の物理条件と次の作業

| 未入力事項 | 必要な段階・決める内容 |
| --- | --- |
| 共通rack interface | M1：1U/2Uの高さ増分，幅/奥行き，rail/穴/締結，公差，datum，module交換の方法 |
| printerと材料 | M2/M3：型番/firmware/controller，build volume，ノズル径，材料/lot，bed，姿勢，実機profile，API可否 |
| 計測 | M4：ノギス等の器具，校正/既知長，測定方法，実試料の識別，環境，不確かさ方針 |
| camera/fixture | M5：実board・module・lens・ケーブルの型番/revision，焦点/解像度，検査距離，拡散照明，背景，平面治具，基準ゲージ |
| 荷重・熱・電気 | M6/通電版：mass/重心，支持・ねじ締結，挿抜力，温度，放熱，電源・絶縁条件 |
| robotと触覚 | M7：robot/把持器，sensor，作業域，接触力・速度上限，停止・通信断・回収手順 |
| integration | M0/M4以降：worker/runtimeのjob/result契約，private evidence保存先と保存方針，採用decisionのowner |

これらが未定の段階は `blocked` または未検証として記録します．文書の公開・softwareの合成検証は進められますが，実印刷・実測成功として数えません．直近の小さな実装PR候補は **M0のread-only接続test** と **M1の共通interface要求・original coupon生成** です．本変更は調査文書と索引だけで，hardware・printer・robot・model・Strataを操作しません．私有mechanism source，ユーザーデータ，生log，検証bundleを公開物へ取り込みません．
