"""
車牌辨識模組(Raspberry Pi 端)。

使用 fast-alpr(底層走 ONNX Runtime,「不需要」PyTorch / TensorFlow):
    偵測:open-image-models 的 YOLOv9-t(yolo-v9-t-384-license-plate-end2end)
    OCR :fast-plate-ocr 的 global 模型(cct-xs-v2-global-model,認 A-Z0-9,適合台灣車牌)

安裝(在 Pi 上,建議 64-bit Raspberry Pi OS / aarch64):
    pip install "fast-alpr[onnx]"

設計重點:
- 模型「只載入一次」(lazy singleton):第一次呼叫 recognize_plate 才載入並下載權重,
  之後重用同一個物件,避免每次門鈴都重載(RPi4 上重載很慢)。
- 若 fast-alpr 尚未安裝或載入失敗,「不會」讓整個 app 掛掉:
  recognize_plate 會回 (None, 0.0),門鈴就退回原本「推照片給管理員」的流程。
"""

import statistics

# 模型名稱(要換模型改這兩個就好)。
# global 模型適合台灣這種純英數車牌;若日後要辨識中國車牌(含省份漢字)才需要換。
DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
OCR_MODEL = "cct-xs-v2-global-model"

_alpr = None           # 已載入的 ALPR 物件(singleton)
_load_failed = False   # 載入失敗就不再重試,避免每次門鈴都卡在載入


def _get_alpr():
    """Lazy 載入 ALPR。第一次呼叫才初始化(會自動下載權重,約數十 MB)。"""
    global _alpr, _load_failed

    if _alpr is not None:
        return _alpr
    if _load_failed:
        return None

    try:
        from fast_alpr import ALPR

        _alpr = ALPR(detector_model=DETECTOR_MODEL, ocr_model=OCR_MODEL)
        print("[plate] ALPR 模型載入完成")
        return _alpr
    except Exception as e:
        _load_failed = True
        print("[plate] 無法載入 fast-alpr,車牌辨識停用:", e)
        print('[plate] 請在 Pi 上安裝:pip install "fast-alpr[onnx]"')
        return None


def load_model():
    """預先載入模型(app 啟動時在背景呼叫,避免第一次門鈴才載入而逾時)。回傳是否成功。"""
    return _get_alpr() is not None


def _to_scalar_confidence(confidence):
    """
    OcrResult.confidence 可能是單一 float,也可能是「每個字元一個 float」的 list。
    統一壓成一個 0~1 的分數(取平均)。
    """
    if confidence is None:
        return 0.0
    if isinstance(confidence, (list, tuple)):
        return float(statistics.mean(confidence)) if confidence else 0.0
    return float(confidence)


def recognize_plate(image):
    """
    對一張影像辨識車牌。

    image: 檔案路徑(str)或 BGR 的 numpy 影像。
    回傳 (plate_text 或 None, confidence float 0~1)。
    若偵測到多張車牌,回傳信心值最高的那一張。
    """
    alpr = _get_alpr()
    if alpr is None:
        return None, 0.0

    try:
        results = alpr.predict(image)
    except Exception as e:
        print("[plate] 辨識過程發生錯誤:", e)
        return None, 0.0

    best_text = None
    best_conf = 0.0

    for r in results:
        # 有偵測到車牌框,但 OCR 沒讀出文字 → 跳過
        if r.ocr is None or not r.ocr.text:
            continue

        conf = _to_scalar_confidence(r.ocr.confidence)
        if conf >= best_conf:
            best_conf = conf
            best_text = r.ocr.text

    return best_text, best_conf


if __name__ == "__main__":
    # 簡易自我測試:python plate_recognition.py <影像路徑>
    import sys

    if len(sys.argv) < 2:
        print("用法:python plate_recognition.py <影像路徑>")
        raise SystemExit(1)

    text, conf = recognize_plate(sys.argv[1])
    print(f"辨識結果:{text!r}  信心值:{conf:.3f}")
