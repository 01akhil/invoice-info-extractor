import cv2
import pytesseract

from config.settings import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

class OCRReader:
    def read(self, img_path):
        img = cv2.imread(img_path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        results = []
        n_boxes = len(data['level'])
        for i in range(n_boxes):
            text = data['text'][i].strip()
            if text:
                left, top, width, height = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                bbox = (left, top, width, height)
                conf = int(data['conf'][i]) / 100
                results.append((conf, text, bbox))
        return img, results



