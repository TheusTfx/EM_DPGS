import unicodedata

_REGIOES = {
    "NOROESTE COLONIAL": ["IJUÍ", "SANTO AUGUSTO", "CÉSAR AUGUSTO", "AJURICABA"],
    "ALTO JACUÍ": ["CRUZ ALTA", "IBIRUBÁ", "SELBACH", "TAPERA", "SALDANHA MARINHO",
                   "SANTA BÁRBARA DO SUL", "QUINZE DE NOVEMBRO"],
    "CELEIRO – ITIBERÊ OSÓRIO": ["TRÊS PASSOS", "FREDERICO WESTPHALEN", "HORIZONTINA",
                                 "PALMEIRA DAS MISSÕES", "SARANDI", "TUCUNDUVA",
                                 "SÃO MARTINHO", "VISTA GAÚCHA"],
    "VINHEDOS": ["BENTO GONÇALVES", "GARIBALDI", "CARLOS BARBOSA", "MONTE BELO DO SUL",
                 "PINTO BANDEIRA", "SANTA TEREZA", "VALE REAL", "NOVA ROMA DO SUL"],
    "ALTO URUGUAI – LEONEL BRIZOLA": ["ERECHIM", "GETÚLIO VARGAS", "ARATIBA", "JACUTINGA",
                                      "SEVERIANO DE ALMEIDA"],
    "GRANDE GUAPORÉ": ["GUAPORÉ", "ENCONSTADO", "MUÇUM", "DOIS LAJEADOS", "COTIPOARA",
                       "COTIPORÃ", "SÉRIO", "PUTINGA", "NOVA BASSANO"],
    "TRABALHISTA DO PLANALTO": ["PASSO FUNDO", "CARAZINHO", "TAPEJARA", "CAMPO NOVO",
                                "CIRÍACO", "COXILHA", "SANTA CECÍLIA DO SUL", "NÃO-ME-TOQUE"],
    "ZONA SUL": ["PELOTAS", "RIO GRANDE", "CAMAQUÃ", "CANGUÇU", "SÃO JOSÉ DO NORTE",
                 "CRISTAL", "TAPES", "ARAMBARÉ", "DOM FELICIANO", "SENTINELA DO SUL",
                 "CHUVISCA"],
    "FRONTEIRA OESTE": ["URUGUAIANA", "ALEGRETE", "SÃO BORJA", "ITAQUI",
                        "BARRA DO QUARAÍ", "QUARAÍ", "MANOEL VIANA", "MAÇAMBARÁ"],
    "FRONTEIRA NOROESTE - PAULO MADEIRA": ["SANTA ROSA", "SANTO CRISTO", "GIRUÁ",
                                           "TRÊS DE MAIO", "TUPARENDI",
                                           "BOA VISTA DO BURICÁ", "NOVO MACHADO"],
    "FRONTEIRA SUDESTE": ["BAGÉ", "DOM PEDRITO", "HERVAL", "PEDRAS ALTAS",
                          "PINHEIRO MACHADO", "ACEGUÁ", "CANDIOTA", "HULHA NEGRA"],
    "VALE DO JACUÍ": ["CACHOEIRA DO SUL", "RIO PARDO", "SOBRADINHO", "CERRO BRANCO",
                      "NOVO CABRAIS", "PANTANO GRANDE", "AGUDO", "PARAÍSO DO SUL"],
    "GRANDE CAXIAS": ["CAXIAS DO SUL", "FLORES DA CUNHA", "SÃO MARCOS",
                      "NOVA PÁDUA", "FARROUPILHA"],
    "JOSÉ AMÉRICO FREIRE": ["SÃO JERÔNIMO", "CHARQUEADAS", "ARROIO DOS RATOS",
                            "ELDORADO DO SUL"],
    "VALE DO ALTO TAQUARI": ["LAJEADO", "ARROIO DO MEIO", "ROCA SALES", "TRAVESSEIRO",
                             "CAPITÃO", "POUSO NOVO", "PROGRESSO", "FORQUETINHA"],
    "ALTO DA SERRA DO BOTUCARAÍ": ["SOLEDADE", "ESPUMOSO", "FONTOURA XAVIER",
                                    "NOVA PALMA", "TUNAS"],
    "GRANDE SANTA MARIA": ["SANTA MARIA", "JÚLIO DE CASTILHOS", "SÃO PEDRO DO SUL",
                            "RESTINGA SÉCA", "TOROPI", "SILVEIRA MARTINS"],
    "ALTO DA SERRA": ["VACARIA", "BOM JESUS", "MONTE ALEGRE DOS CAMPOS",
                       "CAMPESTRE DA SERRA", "SÃO JOSÉ DOS AUSENTES", "JAQUIRANA"],
    "MEDIO ALTO URUGUAI – JOÃO GOULART": ["VICENTE DUTRA", "SÃO PEDRO DAS MISSÕES",
                                          "TRINDADE DO SUL"],
    "GRANDE LAGOA": ["OSÓRIO", "TRAMANDAÍ", "IMBÉ", "XANGRI-LÁ", "MOSTARDAS",
                     "PALMARES DO SUL", "CIDREIRA", "CAPIVARI DO SUL"],
    "LITORAL NORTE": ["TORRES", "ARROIO DO SAL", "DOM PEDRO DE ALCÂNTARA",
                       "TRÊS CACHOEIRAS", "MAQUINÉ", "MORRINHOS DO SUL"],
    "VALE DO PARANHANA": ["TAQUARA", "IGREJINHA", "PAROBÉ", "ROLANTE", "TRÊS COROAS",
                          "SANTA MARIA DO HERVAL"],
    "MILTON GARCIA DUTRA": ["RONDA ALTA", "LIBERATO SALZANO"],
    "METROPOLITANO DELTA DO JACUÍ": ["PORTO ALEGRE", "GRAVATAÍ", "VIAMÃO", "ALVORADA"],
    "VALE DO RIO DOS SINOS": ["NOVO HAMBURGO", "SÃO LEOPOLDO", "ESTEIO"],
    "SERRA": ["GRAMADO", "CANELA", "NOVA PETRÓPOLIS"],
}


def _sem_acento(s):
    s = unicodedata.normalize('NFD', str(s))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper().strip()


MAPA_REGIOES = {_sem_acento(m): reg for reg, muns in _REGIOES.items() for m in muns}


def _regiao_do_mapa(municipio):
    return MAPA_REGIOES.get(_sem_acento(municipio))
