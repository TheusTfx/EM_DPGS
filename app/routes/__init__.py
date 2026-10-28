def registrar_blueprints(app):
    from .main_routes import bp as main_bp
    from .auth_routes import bp as auth_bp
    from .emendas_routes import bp as emendas_bp
    from .usuarios_routes import bp as usuarios_bp
    from .logs_routes import bp as logs_bp
    from .lixeira_routes import bp as lixeira_bp
    from .estatisticas_routes import bp as estatisticas_bp
    from .importacao_routes import bp as importacao_bp
    from .regioes_routes import bp as regioes_bp

    for bp in (main_bp, auth_bp, emendas_bp, usuarios_bp, logs_bp,
               lixeira_bp, estatisticas_bp, importacao_bp, regioes_bp):
        app.register_blueprint(bp)
