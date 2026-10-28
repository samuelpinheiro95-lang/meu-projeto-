from app import legendas, video


def palavras(*itens):
    return [{"inicio": i, "fim": f, "texto": t} for i, f, t in itens]


def test_agrupa_e_desloca_para_o_inicio_do_corte():
    blocos = legendas.agrupar(palavras((10, 10.4, "Oi"), (10.5, 10.9, "gente."), (11.0, 11.4, "Tudo"), (11.5, 11.9, "bem?")), inicio=10)
    assert [b["texto"] for b in blocos] == ["Oi gente.", "Tudo bem?"]
    assert blocos[0]["inicio"] == 0


def test_pausa_longa_quebra_a_legenda():
    blocos = legendas.agrupar(palavras((0, 0.4, "um"), (2.0, 2.4, "dois")))
    assert len(blocos) == 2


def test_srt_formatado():
    srt = legendas.gerar_srt(palavras((3661.5, 3662, "teste")))
    assert "01:01:01,500 --> 01:01:02,000" in srt


def test_filtro_vertical_4k_de_video_horizontal():
    info = {"largura": 1920, "altura": 1080}
    assert video.filtro_de_video(info, "4k", "9:16") == "crop=608:1080,scale=2160:3840:flags=lanczos,setsar=1"


def test_filtro_original_nao_altera():
    assert video.filtro_de_video({"largura": 1920, "altura": 1080}, "original", "original") == "setsar=1"
