import cv2
def bbox_to_int(bbox):
    if bbox is None:
        return None

    if isinstance(bbox, (tuple, list)) and len(bbox) == 4:
        return tuple(map(int, bbox))

    elif isinstance(bbox, list) and isinstance(bbox[0], list):
        xs = [int(p[0]) for p in bbox]
        ys = [int(p[1]) for p in bbox]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
        return x, y, w, h

    elif isinstance(bbox, (float, int)):
        val = int(bbox)
        return val, val, 1, 1

    else:
        raise ValueError(f"Unknown bbox format: {bbox}")

def draw_findings(image, total_bbox=None, date_bbox=None, vendor_bbox=None, vendor_name=None):
    img_copy = image.copy()

    if total_bbox:
        x, y, w, h = bbox_to_int(total_bbox)
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            img_copy, "TOTAL", (x, max(0, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )

    if date_bbox:
        x, y, w, h = bbox_to_int(date_bbox)
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (255, 0, 0), 2)
        cv2.putText(
            img_copy, "DATE", (x, max(0, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2,
        )

    if vendor_bbox:
        x, y, w, h = bbox_to_int(vendor_bbox)
        cv2.rectangle(img_copy, (x, y), (x + w, y + h), (0, 0, 255), 2)

        label = vendor_name or "VENDOR"
        cv2.putText(
            img_copy, label, (x, max(0, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
        )

    return img_copy