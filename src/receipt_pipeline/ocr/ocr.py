import cv2
import pytesseract

from config.settings import TESSERACT_CMD

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

class CorruptedImageError(Exception):
    pass


class OCRReader:
    def read(self, img_path):
        img = cv2.imread(img_path)

        if img is None:
            raise CorruptedImageError(f"Corrupted or unreadable image: {img_path}")

        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT
        )

        results = []
        n_boxes = len(data['level'])

        for i in range(n_boxes):
            text = data['text'][i].strip()
            if text:
                left = data['left'][i]
                top = data['top'][i]
                width = data['width'][i]
                height = data['height'][i]

                bbox = (left, top, width, height)
                conf = int(data['conf'][i]) / 100

                results.append((conf, text, bbox))

        return img, results