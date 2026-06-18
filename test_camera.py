import cv2

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Cannot open camera")
    exit()

ret, frame = cap.read()

if ret:
    cv2.imwrite("test.jpg", frame)
    print("Saved test.jpg")
else:
    print("Failed to capture image")

cap.release()
