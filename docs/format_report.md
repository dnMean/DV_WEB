
<!--
=================================================================
PHẦN HƯỚNG DẪN — ĐỌC KỸ, RỒI XÓA TOÀN BỘ PHẦN NÀY TRƯỚC KHI NỘP
(từ đầu file đến dòng "HẾT PHẦN HƯỚNG DẪN")
=================================================================
-->

# Mẫu báo cáo INT4425 — Hướng dẫn

> **Môn học:** INT4425 — Dịch vụ Web · **Giảng viên:** Đặng Ngọc Hùng
>
> **Ngày nộp, đợt vấn đáp, nơi nộp:** xem **thông báo lớp** của đợt học.
> Mẫu này chỉ quy định **nội dung, hình thức và tiêu chí chấm** — dùng chung cho mọi đợt.

## Lộ trình 2 phiên bản

| Phiên bản                                       | Khi nào                             | Giới hạn                  | Mục tiêu                                                                   |                 Tỷ trọng                 |
| ------------------------------------------------- | ------------------------------------ | --------------------------- | ---------------------------------------------------------------------------- | :-----------------------------------------: |
| **V1** — Báo cáo vấn đáp              | Nộp trước buổi vấn đáp lần 1 | Tối đa **05 trang** | Trình bày đủ ý chính — là căn cứ để hỏi vấn đáp              | **20%** *(+ 20% vấn đáp lần 1)* |
| **V2** — Tiểu luận kết thúc học phần | Sau vấn đáp lần 1                | **10–15 trang**      | Hoàn thiện theo nhận xét vấn đáp, đào sâu — bài thi chính thức | **50%** *(cùng vấn đáp lần 2)* |

Chuyên cần: 10%.

### V1 → V2: Sửa và mở rộng gì?

1. **Sửa** theo nhận xét ở buổi vấn đáp lần 1 — ghi lại trong mục **"Thay đổi sau vấn đáp"** (bắt buộc ở V2).
2. **Mở rộng** ngay **sau** mỗi mục tương ứng — không thêm chương mới. Gợi ý:
   - Ví dụ triển khai chi tiết hơn: code snippet, config, sơ đồ luồng
   - So sánh, trade-off, các biến thể của pattern / công nghệ
   - Thêm use case thực tế, hoặc đào sâu một use case đã có
   - Mở rộng Kết luận cá nhân với nhận thức mới sau vấn đáp

## Quy định trình bày

- **Tên file:** `[STT]_[Mã]_[Tên_ngắn]_[V1|V2].pdf`
  - **STT:** STT nhóm, 2 chữ số (`03`)
  - **Mã:** `Txx` — mã topic (Hoạt động 1) · `Cxx` — số chương, hoặc `PLC`, `PLD`… cho phụ lục (Hoạt động 2)
  - **Tên ngắn:** không dấu, các từ nối bằng `_`
  - Ví dụ: `03_T32_Circuit_Breaker_V1.pdf` · `07_C04_Giao_tiep_dong_bo_V1.pdf` · `11_T55_MCP_V2.pdf`
- **Font** tiêu chuẩn cỡ **13** · căn lề thông thường · **không cần trang bìa**
- Nộp **PDF**; giới hạn trang tính trên file PDF đã xuất
- Chỉ giữ **một** trong hai phần: **A** (Hoạt động 1) hoặc **B** (Hoạt động 2); xóa phần còn lại và mọi comment hướng dẫn
- Mọi khẳng định kỹ thuật quan trọng phải có **trích dẫn** dạng `[1]`, `[2]` trỏ tới mục Tài liệu tham khảo

## Tiêu chí chấm điểm

**Mức chấm cho mỗi tiêu chí:** **Tốt** = 100% số điểm · **Đạt** = 70% · **Yếu** = 40% · **Không có / sai** = 0.
Mỗi mức dưới đây mô tả dấu hiệu **quan sát được trong báo cáo**.

**Nộp muộn** — thời điểm nộp là lúc file được **tải lên hoặc sửa lần cuối** trên Google Drive của lớp; sửa file sau hạn cũng tính là nộp muộn:

| Mức trễ so với hạn                                                                                                        | V1                           | V2                               |
| ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | -------------------------------- |
| Đến 24 giờ                                                                                                                 | trừ **30%** điểm V1 | trừ **30%** điểm V2     |
| Trên 24 giờ                                                                                                                 | trừ **50%** điểm V1 | trừ **50%** điểm V2     |
| Không nộp trước giờ bắt đầu buổi vấn đáp lần 1 *(V1)* / sau thời điểm chốt trong thông báo lớp *(V2)* | V1 = **0**             | Không chấm — V2 = **0** |

**Quy tắc chung:**

- **Vượt giới hạn trang:** chỉ chấm phần nằm trong giới hạn (05 trang với V1, 15 trang với V2).
- **Nguồn không kiểm chứng được** (link không tồn tại, tài liệu không có thật, nội dung không khớp với điều được trích): tiêu chí *Tài liệu tham khảo* = 0, và tiêu chí chứa khẳng định đó tối đa mức **Yếu**.
- **Nhận định chung chung, không có dẫn chứng** ("rất phổ biến", "hiệu năng cao", "nhiều công ty dùng"): tối đa mức **Đạt**.
- **Sai hoạt động / sai topic đã đăng ký:** giảng viên xem xét riêng.

### V1 — thang 10 (quy về 20%)

**Phần chung (3,0 điểm)**

| Mã | Tiêu chí                          | Điểm | Tốt                                                                                                                                                                                    | Dấu hiệu bị trừ                                                                                                     |
| --- | ----------------------------------- | :----: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| H   | Hình thức & quy định            |  1,0  | ≤ 05 trang · cỡ 13 · tên file đúng quy tắc · đã xóa phần không dùng và comment · bảng phân công đủ họ tên, MSSV, phần đảm nhận                              | Thiếu MSSV · còn comment hướng dẫn · còn cả A và B · tên file sai                                           |
| R   | Tài liệu tham khảo & trích dẫn |  1,0  | ≥ 3 nguồn kiểm chứng được · có ít nhất 1 nguồn gốc (tài liệu chính thức, đặc tả, paper, blog kỹ thuật của chính công ty) · thân bài có trích dẫn `[n]` | Chỉ có nguồn tổng hợp (blog SEO, bài dịch lại) · không có trích dẫn trong thân bài                       |
| K   | Kết luận cá nhân                |  1,0  | Mỗi thành viên 50–70 từ, trả lời đủ 3 câu, nêu **cụ thể** khái niệm / trade-off đã thay đổi cách hiểu                                                        | Thiếu thành viên · viết chung chung ("học được nhiều điều bổ ích") · các thành viên viết giống nhau |

**Hoạt động 1 — Phần A (7,0 điểm)**

| Mã | Tiêu chí                              | Điểm | Tốt                                                                                                                    | Dấu hiệu bị trừ                                                                      |
| --- | --------------------------------------- | :----: | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| A1  | Vấn đề & bối cảnh                  |  1,5  | Nêu rõ bài toán cụ thể mà pattern / công nghệ giải quyết · có mốc năm, tổ chức / tác giả             | Chỉ định nghĩa, không nêu bài toán · không có mốc lịch sử                  |
| A2  | Cách hoạt động                      |  2,5  | Nêu đủ thành phần chính và vai trò · luồng xử lý từng bước · có sơ đồ khớp với lời giải thích  | Chỉ liệt kê tên thành phần · sơ đồ không khớp với mô tả · sai kỹ thuật |
| A3  | Ứng dụng thực tế                    |  1,5  | 1–2 use case có tên công ty / dự án, bài toán cụ thể, lý do chọn, kết quả (nếu công khai) · có nguồn | Use case giả định hoặc không có nguồn                                             |
| A4  | Đánh giá — nên / không nên dùng |  1,5  | Ưu và nhược điểm cụ thể · điều kiện **nên** và **không nên** dùng rõ ràng                | Chỉ có ưu điểm · thiếu "không nên dùng khi"                                    |

**Hoạt động 2 — Phần B (7,0 điểm)**

| Mã | Tiêu chí                | Điểm | Tốt                                                                                                                                                                                                                                                                                                                  | Dấu hiệu bị trừ                                                                                                                              |
| --- | ------------------------- | :----: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| B0  | Nhóm hiểu gì về topic |  2,0  | Tóm tắt đúng bài toán của chương · kể tên ≥ 2 nguồn **ngoài sách** đã dùng để tự học · nêu điều nhóm học được từ các nguồn đó                                                                                                                                              | Chỉ tóm tắt lại chương · không có nguồn ngoài                                                                                         |
| B1  | Trình bày               |  1,0  | Nhận xét cấu trúc có lý do · đề xuất có vị trí cụ thể ("mục 4.3 nên đặt trước 4.2 vì…")                                                                                                                                                                                                        | Chỉ nói "ổn", "dễ hiểu" không lý do                                                                                                       |
| B2  | Nội dung                 |  2,0  | Chỉ ra chỗ thiếu / sai / lỗi thời **cụ thể**, mỗi điểm có **vị trí** (mục, đoạn) và **nguồn** đối chiếu                                                                                                                                                                        | Nói "thiếu" mà không nêu thiếu gì · không có nguồn đối chiếu                                                                       |
| B3  | Thuật ngữ               |  1,0  | Bảng: thuật ngữ gốc → cách dùng trong sách → đề xuất, có lý do · đối chiếu Phụ lục A (Bảng thuật ngữ)                                                                                                                                                                                          | Không có ví dụ cụ thể                                                                                                                      |
| B4  | Đề xuất cụ thể       |  1,0  | **Review:** tối đa 0,5 — ≥ 5 đề xuất có vị trí và cách sửa · **Improve / Contribute:** tối đa 1,0 — có bản sửa hoàn chỉnh (đoạn viết lại, ví dụ, hình); với Contribute, bảng GitHub Issue ghi đủ số Issue, tiêu đề, link, trạng thái và Issue có chứa bản sửa | Đề xuất không có vị trí · không có nội dung sửa · ghi Contribute nhưng thiếu thông tin Issue hoặc link Issue không mở được |

### V2 — thang 10 (là một phần của điểm thi 50%, cùng vấn đáp lần 2)

| Mã | Tiêu chí                                    | Điểm | Tốt                                                                                                                                                                                                   | Dấu hiệu bị trừ                                                          |
| --- | --------------------------------------------- | :----: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| H   | Hình thức & quy định                      |  0,5  | 10–15 trang · tên file `_V2` · giữ đúng khung mục của V1                                                                                                                                    | Dưới 10 hoặc trên 15 trang · đổi khung mục                           |
| S   | Tiếp thu nhận xét vấn đáp               |  1,5  | Mục **"Thay đổi sau vấn đáp"** liệt kê từng nhận xét → đã sửa ở mục nào                                                                                                        | Không có mục này · nhận xét được ghi nhưng nội dung không đổi |
| N   | Nội dung cốt lõi *(A1–A4 hoặc B0–B4)* |  4,0  | Chấm lại như tiêu chí V1 tương ứng, trên bản đã sửa: đầy đủ, chính xác                                                                                                              | Lỗi đã được nhận xét ở vấn đáp vẫn còn                         |
| D   | Chiều sâu phần mở rộng                   |  2,5  | Có ít nhất 2 trong 4: ví dụ triển khai (code / config chạy được hoặc đọc hiểu được) · so sánh / trade-off với giải pháp thay thế · use case bổ sung · biến thể / edge case | Phần thêm chỉ kéo dài câu chữ, không thêm hiểu biết mới          |
| R   | Tài liệu tham khảo                         |  0,5  | ≥ 5 nguồn kiểm chứng được, có nguồn **mới** so với V1                                                                                                                                 | Giữ nguyên danh sách V1                                                   |
| K   | Kết luận cá nhân                          |  1,0  | Có phần bổ sung sau vấn đáp: câu hỏi nào khiến phải nghĩ lại, nhận thức nào thay đổi                                                                                                 | Giữ nguyên như V1                                                         |

<!--
=================================================================
HẾT PHẦN HƯỚNG DẪN — BẢN NỘP BẮT ĐẦU TỪ TIÊU ĐỀ BÊN DƯỚI
=================================================================
-->

# Nhóm [STT] — [Mã Txx/Cxx] — [Tên Topic / Tên Chương]

> **Môn học:** INT4425 — Dịch vụ Web · **Giảng viên:** Đặng Ngọc Hùng
>
> **Phiên bản:** ☐ V1 &nbsp;☐ V2 &nbsp;·&nbsp; **Đợt vấn đáp:** ☐ Đợt 1 &nbsp;☐ Đợt 2
>
> ☐ **Hoạt động 1** — Nghiên cứu topic *(dùng Phần A, xóa Phần B)*
> ☐ **Hoạt động 2** — Review / góp ý sách *(dùng Phần B, xóa Phần A)*

---

## Thành viên & Phân công

| Họ tên | MSSV | Phần đảm nhận (mục) | Mức đóng góp                              |
| -------- | ---- | ------------------------ | --------------------------------------------- |
|          |      |                          | ☐ Chính &nbsp;☐ Hỗ trợ &nbsp;☐ Tham gia |
|          |      |                          | ☐ Chính &nbsp;☐ Hỗ trợ &nbsp;☐ Tham gia |
|          |      |                          | ☐ Chính &nbsp;☐ Hỗ trợ &nbsp;☐ Tham gia |

> ⚠️ **Vấn đáp:** Mỗi thành viên được hỏi về **phần mình làm và đang hiểu**.
> Câu hỏi bám sát nội dung báo cáo — trình bày đến đâu, hỏi đến đó.

---

<!--
=================================================================
PHẦN A — HOẠT ĐỘNG 1: Nghiên cứu topic
XÓA PHẦN B TRƯỚC KHI NỘP.
Ước lượng V1 (05 trang): A1 ~150 từ · A2 ~200 từ + sơ đồ · A3 ~150 từ · A4 ~100 từ.
=================================================================
-->

## A. Nghiên cứu Topic

### A1. Vấn đề & Bối cảnh

<!--
V1 (~150 từ): Trả lời 3 câu:
  - Bài toán nào khiến pattern / công nghệ này ra đời?
  - Nó xuất hiện trong bối cảnh nào của lịch sử phát triển phần mềm?
  - Tại sao nó được adopt rộng rãi — hay tại sao chưa phổ biến?
Dẫn chứng có năm, có tên tổ chức / tác giả cụ thể.

V2 (mở rộng): Bổ sung dẫn chứng, số liệu, hoặc so sánh với các giải pháp cũ hơn.
-->

*(Viết tại đây)*

---

### A2. Cách hoạt động

<!--
V1 (~200 từ + sơ đồ):
  - Mô tả các thành phần chính là gì, làm gì
  - Luồng xử lý từng bước — dùng sơ đồ ASCII hoặc hình ảnh
  - Nếu có nhiều biến thể, chọn một biến thể chính để trình bày

V2 (mở rộng): Trình bày thêm biến thể, edge case,
và một đoạn code / config minh họa cụ thể.
Không cần chạy được hoàn toàn — nhưng đủ để đọc hiểu được.
-->

*(Viết tại đây)*

```
Sơ đồ minh họa (thay hoặc xóa nếu không phù hợp):

  Client ──► [A] ──► [B] ──► [C]
                 └──► [D]
```

```text
Code / config minh họa (V2 — đổi ngôn ngữ của khối cho phù hợp)
V1: có thể để trống hoặc dùng pseudocode ngắn
```

---

### A3. Ứng dụng thực tế

<!--
V1 (~150 từ):
  - 1–2 use case có tên công ty / dự án, mô tả bài toán cụ thể
  - Tại sao họ chọn giải pháp này thay vì cách khác?
  - Kết quả / lợi ích đo được (nếu có số liệu công khai)
  Tránh nói chung chung — ưu tiên dẫn chứng có thể kiểm chứng.

V2 (mở rộng): Thêm 1 use case nữa, hoặc đào sâu 1 use case đã có.
Có thể thêm phần "Bài học từ thực tế" ngắn.

Nếu có tài liệu chi tiết hơn (repo, gist, bài viết kỹ thuật),
để link ở đây thay vì nhét hết nội dung vào trang báo cáo.
-->

*(Viết tại đây)*

> 📎 *Tài liệu / repo đính kèm (nếu có): [link]*

---

### A4. Đánh giá — Khi nào nên / không nên dùng

<!--
V1 (~100 từ):
  - Ưu điểm nổi bật nhất (2–3 điểm)
  - Nhược điểm / hạn chế cần biết (2–3 điểm)
  - Nên dùng khi: ...
  - Không nên dùng khi: ...

V2 (mở rộng): So sánh với pattern / công nghệ thay thế,
hoặc ma trận quyết định đơn giản.
-->

**Ưu điểm:**

- *(điền tại đây)*

**Nhược điểm / Hạn chế:**

- *(điền tại đây)*

**Nên dùng khi:** *(điền tại đây)*

**Không nên dùng khi:** *(điền tại đây)*

---

<!--
=================================================================
PHẦN B — HOẠT ĐỘNG 2: Review / góp ý sách
XÓA PHẦN A TRƯỚC KHI NỘP.

Quan trọng: Đây là hoạt động HỌC.
Để review có giá trị, nhóm phải tự tìm hiểu topic từ nhiều
nguồn bên ngoài trước — rồi mới đọc sách để đánh giá.

Ghi VỊ TRÍ theo số mục của bản đọc online, ví dụ "mục 4.3, đoạn 2".
=================================================================
-->

## B. Review / Góp ý Sách

> **Sách:** [hungdn1701.github.io/ptit-microservice-textbook](https://hungdn1701.github.io/ptit-microservice-textbook/)
> **Chương / phụ lục:** `___` — **Chủ đề:** `___`
> **Mức:** ☐ Review &nbsp;☐ Improve &nbsp;☐ Contribute *(GitHub Issue)*

### B0. Nhóm hiểu gì về topic này

<!--
V1 (~150 từ) — phần quan trọng nhất:
  - Topic này giải quyết bài toán gì?
  - Nhóm đã tìm hiểu từ nguồn nào ngoài chương được giao?
    (tài liệu chính thức, blog kỹ thuật, paper, video, repo mẫu...)
  - Điều gì thú vị hoặc bất ngờ khi tìm hiểu?
Phần này cho thấy nhóm đã chủ động học — không chỉ đọc để tìm lỗi.

V2 (mở rộng): Tóm tắt sâu hơn về topic,
hoặc ghi lại quá trình tìm hiểu (đọc gì, học được gì theo từng nguồn).
-->

*(Viết tại đây)*

---

### B1. Trình bày

<!--
V1:
  Cấu trúc có rõ ràng không? Luồng dẫn dắt có logic không?
  Người mới đọc có theo được không?
  Đề xuất cụ thể: "mục X nên đặt trước mục Y vì..."
  Nếu cấu trúc tốt thì nói rõ tại sao tốt — không chỉ "ổn rồi".

V2: Bổ sung ví dụ về cách tổ chức tốt hơn,
hoặc so sánh với cách trình bày trong tài liệu khác về cùng topic.
-->

*(Viết tại đây)*

---

### B2. Nội dung

<!--
V1:
  Có đủ và chính xác không — dựa trên những gì nhóm tìm hiểu?
  "Mục 5.4 thiếu X vì theo [nguồn], thực tế là..."
  "Mục 7.2 có vẻ không còn chính xác vì phiên bản mới đã thay đổi..."
  Không được chỉ nói "thiếu" mà không nêu thiếu cái gì cụ thể.

V2: Bổ sung nội dung còn thiếu mà nhóm đã xác định ở V1,
với phân tích đầy đủ hơn về lý do tại sao nên thêm phần đó.
-->

*(Viết tại đây)*

---

### B3. Thuật ngữ

<!--
V1:
  Nhất quán xuyên suốt chương không? Khớp với Phụ lục A (Bảng thuật ngữ) không?
  Dịch tiếng Việt có chính xác và tự nhiên không?
  Ví dụ: "microservices" → "vi dịch vụ" (không tự nhiên) → giữ nguyên tiếng Anh.

V2: Chỉ cập nhật nếu phát hiện thêm.
-->

| Thuật ngữ gốc | Cách dùng trong sách (vị trí) | Đề xuất | Lý do |
| ---------------- | ---------------------------------- | ---------- | ------ |
|                  |                                    |            |        |

---

### B4. Đề xuất cụ thể

<!--
Bắt buộc với mọi mức:
  - Review: danh sách ≥ 5 đề xuất, mỗi đề xuất có VỊ TRÍ + CÁCH SỬA.
  - Improve: kèm bản sửa hoàn chỉnh (đoạn viết lại, ví dụ bổ sung, hình vẽ lại).
  - Contribute: mở GitHub Issue trên repo sách, dán bản sửa vào Issue,
    và ghi đủ thông tin Issue vào bảng bên dưới.

Khuyến khích MỌI mức mở Issue cho đề xuất của mình — càng nhiều Issue có chất lượng càng tốt.
  - Mở tại: https://github.com/hungdn1701/ptit-microservice-textbook/issues/new
  - Tiêu đề Issue: [INT4425][Cxx] Nhóm STT — tóm tắt ngắn
    ví dụ: [INT4425][C04] Nhóm 07 — Thiếu ví dụ timeout cho OpenFeign
  - Nội dung Issue: vị trí (mục, đoạn) · vấn đề · nguồn đối chiếu · bản sửa đề xuất.
  - Mỗi Issue một vấn đề.

V2: Cập nhật trạng thái Issue (đã được phản hồi / đóng chưa?), hoặc bổ sung đề xuất.
-->

| # | Vị trí | Vấn đề | Đề xuất sửa | Issue        |
| - | -------- | --------- | --------------- | ------------ |
| 1 |          |           |                 | #… hoặc — |

**GitHub Issue đã mở** *(bắt buộc với mức Contribute; xóa bảng nếu không mở Issue nào)*:

| Issue | Tiêu đề | Link | Ngày mở | Trạng thái khi nộp                            |
| ----- | ---------- | ---- | --------- | ------------------------------------------------ |
| #…   |            |      |           | ☐ Open &nbsp;☐ Đã phản hồi &nbsp;☐ Closed |

> 📎 *File đính kèm (nếu có): [link]*

---

## Kết luận & Bài học cá nhân

<!--
V1: 50–70 từ / người — viết riêng từng thành viên.
Trả lời 3 câu:
  1. Trước khi làm, bạn biết / nghĩ gì về chủ đề này?
  2. Sau khi làm xong, điều gì thực sự mới hoặc thay đổi trong cách bạn hiểu?
  3. Nếu gặp vấn đề này trong công việc thực tế, bạn sẽ tiếp cận thế nào?

V2: Bổ sung sau buổi vấn đáp:
  - Câu hỏi vấn đáp nào khiến bạn phải suy nghĩ lại?
  - Nhận thức nào thay đổi sau khi nghe nhóm khác trình bày?

Tránh viết kiểu "Em học được rất nhiều điều bổ ích" —
nêu cụ thể: khái niệm nào, trade-off nào, quan điểm nào thay đổi.
-->

**[Họ tên 1]:**
*(V1: 50–70 từ)*
*(V2: thêm phần sau vấn đáp)*

**[Họ tên 2]:**
*(V1: 50–70 từ)*
*(V2: thêm phần sau vấn đáp)*

**[Họ tên 3]:** *(nếu có)*
*(V1: 50–70 từ)*
*(V2: thêm phần sau vấn đáp)*

---

## Tài liệu tham khảo

<!--
V1: tối thiểu 3 nguồn · V2: tối thiểu 5 nguồn, có nguồn mới so với V1.
Mọi nguồn phải kiểm chứng được (có link / DOI / ISBN). Nguồn không có thật = 0 điểm mục này.
Ưu tiên: tài liệu chính thức, đặc tả, paper, sách, blog kỹ thuật của chính công ty.
Format: [n] Tác giả, "Tiêu đề", Nguồn, Năm. Link.
-->

---

## Thay đổi sau vấn đáp *(chỉ V2 — bắt buộc)*

<!-- Xóa mục này ở V1. -->

| # | Nhận xét tại vấn đáp lần 1 | Đã sửa / bổ sung ở mục |
| - | --------------------------------- | ---------------------------- |
| 1 |                                   |                              |

---

<!--
=================================================================
CHECKLIST TRƯỚC KHI NỘP — XÓA KHỎI BẢN NỘP

V1 — tối đa 05 trang
- [ ] Đã đánh dấu Phiên bản, Đợt vấn đáp, Hoạt động ở đầu trang
- [ ] Đã xóa Phần Hướng dẫn, phần không dùng (A hoặc B), mục "Thay đổi sau vấn đáp" và mọi comment
- [ ] Bảng phân công đủ họ tên, MSSV, phần đảm nhận
- [ ] Tối đa 05 trang sau khi xuất PDF · font cỡ 13
- [ ] Tên file đúng: [STT]_[Mã]_[Tên_ngắn]_V1.pdf
- [ ] Mỗi thành viên đã viết Kết luận cá nhân (50–70 từ)
- [ ] ≥ 3 nguồn kiểm chứng được · thân bài có trích dẫn [n]
- [ ] (Hoạt động 2) Mọi GitHub Issue đã mở đều có trong bảng Issue: số, tiêu đề, link, trạng thái
- [ ] Nộp lên Google Drive lớp đúng hạn trong thông báo lớp — không sửa file sau hạn

V2 — 10–15 trang
- [ ] Có mục "Thay đổi sau vấn đáp", mỗi nhận xét trỏ tới mục đã sửa
- [ ] Nội dung mở rộng đặt sau các mục tương ứng (không thêm chương mới)
- [ ] Đã cập nhật Kết luận cá nhân sau vấn đáp
- [ ] ≥ 5 nguồn, có nguồn mới so với V1
- [ ] 10–15 trang sau khi xuất PDF · tên file ..._V2.pdf
- [ ] Nộp theo hướng dẫn trong thông báo lớp
=================================================================
-->

*INT4425 — Dịch vụ Web · Đặng Ngọc Hùng · [hungdn1701.github.io](https://hungdn1701.github.io)*
