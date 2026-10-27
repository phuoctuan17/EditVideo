# Auto Video Editor (Local & Zero-API Cost)

Biên tập video tự động chạy hoàn toàn trên máy tính cá nhân (100% Free / Zero API cost), tối ưu cho GPU NVIDIA (RTX 4050 NVENC) và giao diện hỗ trợ cả **Máy tính** lẫn **Điện thoại di động**.

---

## 🌟 Toàn bộ tính năng đã hoàn thiện

### 1. 🔍 Cắt khoảng lặng thông minh (Smart Silence Remover)
- Tự động phát hiện và cắt bỏ các đoạn im lặng/ngập ngừng kéo dài hơn `X` giây bằng bộ lọc `silencedetect`.
- Hình và tiếng được cắt ghép đồng thời theo frame-accurate, không bao giờ bị lệch tiếng (A/V sync).
- Xem trước trực quan trên thanh **Timeline** (đoạn xanh giữ lại, đoạn hồng bị cắt).

### 2. 🎤 Auto Karaoke Subtitles & Trình sửa trực quan (Interactive Subtitle Editor)
- Trích xuất audio và nhận diện từng từ bằng **Faster-Whisper** (`base` hoặc `small`).
- Xuất file `.ass` với hiệu ứng đổi màu chữ từng từ `\kf` kiểu CapCut.
- Cỡ chữ cân đối chuẩn CapCut (36px - 66px), tuỳ chọn màu sắc highlight nổi bật.
- **Trình sửa phụ đề trực quan (Interactive Subtitle Editor):** Bấm nút `✏️ Mở trình chỉnh sửa từng câu phụ đề` để xem và sửa lại chính tả, tên riêng, tiếng lóng trước khi in cứng vào video.

### 3. 🤖 AI Content & Script Generator (Tự viết kịch bản theo video)
- Tự động đo thời lượng video để viết kịch bản có số từ vừa khít thời lượng (không bị dài/ngắn quá).
- Tự động bóc tách lời thoại gốc để nắm bắt ngữ cảnh video.
- 5 phong cách thịnh hành:
  1. 🔥 TikTok / Reels bắt trend (Hook mở đầu giật gân).
  2. ⭐ Đánh giá / Review sản phẩm chân thực.
  3. 📖 Kể chuyện cảm xúc / Truyền cảm hứng.
  4. 🎯 Bán hàng / Kêu gọi hành động.
  5. ⚡ Tin tức nhanh / Tóm tắt súc tích.
- Hỗ trợ nguồn AI: Tự động (Offline + Free), Google Gemini Free API, hoặc Ollama Local (100% Offline).

### 4. 🗣️ Lồng tiếng Neural tiếng Việt & Audio Ducking
- Sử dụng giọng đọc Neural tiếng Việt miễn phí từ `edge-tts`: Hoài My (nữ) và Nam Minh (nam).
- Tự động trộn nhạc nền (BGM) với hiệu ứng **Audio Ducking** (tự động hạ nhỏ âm lượng nhạc nền khi có tiếng nói).

### 5. ✨ Hiệu ứng hình ảnh & Màu sắc (Visual Effects & LUTs)
- **Auto Zoom (Dynamic Punch-in):** Tự động phóng to nhẹ 1.15x đổi nhịp mỗi 4 giây tạo cảm giác multicam sinh động cho video TikTok/Reels.
- **Bộ lọc màu điện ảnh (LUTs):** 1-Click đổi màu (Điện ảnh Teal & Orange, Tone ấm Pastel, Tone lạnh Hàn Quốc, Tươi sáng rực rỡ, Cổ điển Vintage).
- **Watermark / Chữ ký kênh:** Tự động in chữ ký kênh ở góc video.

### 6. 📱 Giao diện tối ưu cho Điện thoại & Máy tính (Mobile Responsive)
- Hệ thống điều hướng Tab thông minh trên màn hình nhỏ.
- Phím bấm và thanh trượt tối ưu cho thao tác chạm vuốt (Touch-friendly).
- Server mở cổng `0.0.0.0:8080`, cho phép mở trên trình duyệt điện thoại cùng mạng Wi-Fi:
  👉 **`http://192.168.1.28:8080`**

---

## 🚀 Cách chạy ứng dụng

```powershell
# 1. Kích hoạt môi trường ảo
.venv\Scripts\activate

# 2. Khởi động ứng dụng
python run.py
```
- Mở trên máy tính: **`http://127.0.0.1:8080`**
- Mở trên điện thoại (cùng Wi-Fi): **`http://192.168.1.28:8080`**
