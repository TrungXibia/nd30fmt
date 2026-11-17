"""Bản thảo mẫu cho 10 mẫu NĐ30 (1.1–1.10) và văn bản Đảng – dùng cho kiểm thử và sinh file Word kiểm tra."""

ORG = {"co_quan_chu_quan": "BỘ X",
       "co_quan_ban_hanh": "VIỆN NGHIÊN CỨU Y",
       "ma_co_quan": "VNCY", "dia_danh": "Hà Nội", "ngay": "2026-01-05", "so": "7",
       "chuc_vu": "VIỆN TRƯỞNG", "ho_ten": "Nguyễn Văn A", "luu": "VP, NVB(05)"}
CHU_THE = "Viện Nghiên cứu Y"


def _d(type_id, **fields):
    return {"standard": "nd30", "type_id": type_id, "fields": {**ORG, **fields}}


NQ = _d("NGHI_QUYET", trich_yeu="Về kế hoạch nghiên cứu năm 2026", tham_quyen="HỘI ĐỒNG KHOA HỌC VIỆN",
        can_cu=["Căn cứ Quyết định số 12/QĐ-BX ngày 03 tháng 01 năm 2025 của Bộ trưởng Bộ X",
                "Căn cứ kết quả phiên họp ngày 02 tháng 01 năm 2026"],
        noi_dung=[{"type": "dieu", "html": "Thông qua kế hoạch nghiên cứu năm 2026."},
                  {"type": "dieu", "html": "Giao Viện trưởng tổ chức thực hiện."}],
        noi_nhan=["Như Điều 2", "Bộ X"])

QD_TRUC_TIEP = _d(
    "QUYET_DINH_TRUC_TIEP", trich_yeu="Về việc thành lập Tổ công tác chuyển đổi số",
    tham_quyen="VIỆN TRƯỞNG VIỆN NGHIÊN CỨU Y",
    can_cu=["Quyết định số 3502/QĐ-BX ngày 05 tháng 12 năm 2023 của Bộ trưởng Bộ X quy định chức năng, "
            "nhiệm vụ, quyền hạn và cơ cấu tổ chức của Viện;"],
    de_nghi="Trưởng phòng Tổ chức – Hành chính",
    noi_dung=[{"type": "dieu", "html": "Thành lập Tổ công tác chuyển đổi số gồm các ông (bà) sau:"},
              {"type": "khoan", "html": "Ông Nguyễn Văn B – Phó Viện trưởng, Tổ trưởng;"},
              {"type": "khoan", "html": "Bà Trần Thị C – Trưởng phòng, Tổ viên."},
              {"type": "dieu", "html": "Tổ công tác có nhiệm vụ:"},
              {"type": "diem", "html": "Xây dựng kế hoạch chuyển đổi số;"},
              {"type": "diem", "html": "Theo dõi, đôn đốc thực hiện."},
              {"type": "dieu", "html": "Quyết định này có hiệu lực kể từ ngày ký."}],
    noi_nhan=["Như Điều 3", "Bộ X (để b/c)"])

QD_GIAN_TIEP = _d(
    "QUYET_DINH_GIAN_TIEP", trich_yeu="Ban hành Quy chế chi tiêu nội bộ",
    tham_quyen="VIỆN TRƯỞNG VIỆN NGHIÊN CỨU Y",
    can_cu=["Căn cứ Nghị định số 60/2021/NĐ-CP ngày 21 tháng 6 năm 2021 của Chính phủ"],
    de_nghi="Kế toán trưởng", hinh_thuc_dieu1="Ban hành",
    van_ban_kem_theo="Quy chế chi tiêu nội bộ của Viện Nghiên cứu Y",
    noi_dung=[{"type": "dieu", "html": "Quyết định này có hiệu lực kể từ ngày ký."},
              {"type": "dieu", "html": "Chánh Văn phòng, Kế toán trưởng chịu trách nhiệm thi hành Quyết định này."}],
    noi_nhan=["Như Điều 3"])

KE_HOACH = _d("KE_HOACH", so="3", trich_yeu="Tổ chức hội thảo khoa học năm 2026",
              noi_dung=[{"type": "la_ma", "html": "Mục đích, yêu cầu"},
                        {"type": "khoan", "html": "Mục đích", "tieu_de": True},
                        {"type": "p", "html": "Trao đổi kết quả nghiên cứu."},
                        {"type": "la_ma", "html": "Nội dung"},
                        {"type": "bullet", "html": "Thời gian: tháng 5 năm 2026;"},
                        {"type": "bullet", "html": "Địa điểm: Hà Nội."}],
              noi_nhan=["Các phòng, trung tâm"])

TO_TRINH = _d("TO_TRINH", trich_yeu="Về việc phê duyệt đề cương nhiệm vụ", kinh_gui=["Bộ trưởng Bộ X"],
              noi_dung=[{"type": "p", "html": "Viện kính trình Bộ trưởng xem xét, phê duyệt."}],
              noi_nhan=["Như trên"])

CONG_VAN = _d("CONG_VAN", ma_don_vi="NL", trich_yeu="góp ý dự thảo Kế hoạch phát triển năng lượng",
              kinh_gui=["Vụ Kế hoạch – Tài chính", "Cục Điện lực"],
              noi_dung=[{"type": "p", "html": "Phúc đáp Công văn số 0123/BCT-KH ngày 02 tháng 01 năm 2026, Viện có ý kiến như sau:"},
                        {"type": "khoan", "html": "Về bố cục: đề nghị bổ sung mục đánh giá tác động."},
                        {"type": "khoan", "html": "Về số liệu: cập nhật số liệu năm 2025."}],
              noi_nhan=["Như trên", "Lãnh đạo Viện"],
              lien_he="Số 1 phố A, phường B, Hà Nội; ĐT: 024 0000 0000; E-mail: vanthu@example.gov.vn")

CONG_DIEN = _d("CONG_DIEN", trich_yeu="Về việc ứng phó bão số 3", nguoi_dien="VIỆN TRƯỞNG VIỆN NGHIÊN CỨU Y",
               noi_nhan_dien=["Các phòng, trung tâm thuộc Viện", "Văn phòng Viện"],
               noi_dung=[{"type": "p", "html": "Yêu cầu các đơn vị chủ động phương án bảo vệ tài liệu, thiết bị."}],
               noi_nhan=["Như trên"])

GIAY_MOI = _d("GIAY_MOI", trich_yeu="Dự hội thảo khoa học", chu_the=CHU_THE,
              nguoi_duoc_moi="Ông (bà) Trưởng phòng Nghiên cứu Z",
              cuoc_hop="Hội thảo “Chuyển dịch năng lượng giai đoạn 2026–2030”", chu_tri="Ông Nguyễn Văn A, Viện trưởng",
              thoi_gian="08 giờ 30, ngày 15 tháng 01 năm 2026", dia_diem="Phòng họp tầng 3, số 46 Ngô Quyền, Hà Nội",
              luu_y=[{"type": "p", "html": "Đề nghị đại biểu xác nhận tham dự trước ngày 12 tháng 01 năm 2026"}],
              noi_nhan=["Như trên"])

GIAY_GIOI_THIEU = _d("GIAY_GIOI_THIEU", chu_the=CHU_THE, nguoi_duoc_gt="Trần Văn D, Phòng Nghiên cứu Z",
                     chuc_vu_gt="Nghiên cứu viên", cu_den="Tập đoàn Điện lực Việt Nam",
                     ve_viec="Thu thập số liệu phục vụ nhiệm vụ nghiên cứu", gia_tri_den="31/01/2026")

BIEN_BAN = {"standard": "nd30", "type_id": "BIEN_BAN", "fields": {
    k: v for k, v in ORG.items() if k not in ("dia_danh", "ngay", "chuc_vu", "ho_ten")} | {
    "trich_yeu": "Họp giao ban tháng 01 năm 2026", "thoi_gian_bat_dau": "08 giờ 00, ngày 05 tháng 01 năm 2026",
    "dia_diem": "Phòng họp tầng 2", "thanh_phan": "Lãnh đạo Viện; Trưởng các phòng, trung tâm",
    "chu_toa": "Ông Nguyễn Văn A, Viện trưởng", "thu_ky": "Bà Lê Thị E, Chuyên viên",
    "noi_dung": [{"type": "p", "html": "Các đơn vị báo cáo kết quả công tác tháng 12 năm 2025."},
                 {"type": "p", "html": "Viện trưởng kết luận và giao nhiệm vụ."}],
    "loai_su_kien": "Cuộc họp", "ket_thuc": "11 giờ 00, ngày 05 tháng 01 năm 2026",
    "ho_ten_thu_ky": "Lê Thị E", "ho_ten_chu_toa": "Nguyễn Văn A", "noi_nhan": ["Lãnh đạo Viện"], "luu": "Hồ sơ"}}

GIAY_NGHI_PHEP = _d("GIAY_NGHI_PHEP", ngay_don="02/01/2026", nguoi_de_nghi="Phạm Văn G", chu_the=CHU_THE,
                    nguoi_nghi="Phạm Văn G, Phòng Nghiên cứu Z", chuc_vu_nguoi_nghi="Chuyên viên",
                    thoi_gian_nghi="05 ngày", tu_ngay="12/01/2026", den_ngay="16/01/2026", noi_nghi="Nam Định",
                    tinh_vao="nghỉ hằng năm có hưởng lương năm 2026", hien_xac_nhan=True)

PARTY = {"standard": "hd05", "type_id": "NGHI_QUYET", "fields": {
    "co_quan_chu_quan": "ĐẢNG BỘ BỘ X", "co_quan_ban_hanh": "ĐẢNG ỦY VIỆN NGHIÊN CỨU Y",
    "ma_co_quan": "ĐU", "so": "12", "dia_danh": "Hà Nội", "ngay": "2026-01-05",
    "trich_yeu": "về lãnh đạo thực hiện nhiệm vụ chính trị năm 2026",
    "noi_dung": [{"type": "la_ma", "html": "Tình hình"}, {"type": "p", "html": "Năm 2025, Đảng bộ đã lãnh đạo hoàn thành nhiệm vụ."}],
    "noi_nhan": ["Đảng ủy Bộ", "Các chi bộ"], "luu": "Văn phòng Đảng ủy",
    "quyen_han": "T/M", "quyen_han_cua": "ĐẢNG ỦY", "chuc_vu": "BÍ THƯ", "ho_ten": "Nguyễn Văn H"}}

ALL_ND30 = {"1.1": NQ, "1.2": QD_TRUC_TIEP, "1.3": QD_GIAN_TIEP, "1.4": KE_HOACH, "1.5": CONG_VAN, "1.6": CONG_DIEN,
            "1.7": GIAY_MOI, "1.8": GIAY_GIOI_THIEU, "1.9": BIEN_BAN, "1.10": GIAY_NGHI_PHEP}
