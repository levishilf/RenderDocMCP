# RenderDoc MCP Server

RenderDoc UI拡張機能として動作するMCPサーバー。AIアシスタントがRenderDocのキャプチャデータにアクセスし、DirectX 11/12のグラフィックスデバッグを支援する。

## アーキテクチャ

**ハイブリッドプロセス分離方式**:

```
Claude/AI Client (stdio)
        │
        ▼
MCP Server Process (標準Python + FastMCP 2.0)
        │ TCP Socket (127.0.0.1:19876)
        ▼
RenderDoc Process (Extension + Socket Server)
```

## プロジェクト構成

```
RenderDocMCP/
├── mcp_server/                        # MCPサーバー
│   ├── server.py                      # FastMCPエントリーポイント
│   ├── config.py                      # 設定
│   └── bridge/
│       └── client.py                  # Socket通信クライアント
│
├── renderdoc_extension/               # RenderDoc拡張機能
│   ├── __init__.py                    # register()/unregister()
│   ├── extension.json                 # マニフェスト
│   ├── socket_server.py               # TCPソケットサーバー
│   ├── request_handler.py             # リクエスト処理
│   └── renderdoc_facade.py            # RenderDoc APIラッパー
│
└── scripts/
    └── install_extension.py           # 拡張機能インストール
```

## MCPツール

| ツール名 | 説明 |
|---------|------|
| `get_capture_status` | キャプチャ読込状態確認 |
| `get_draw_calls` | ドローコール一覧（階層構造） |
| `get_draw_call_details` | 特定ドローコールの詳細 |
| `get_shader_info` | シェーダーソース/定数バッファ |
| `get_buffer_contents` | バッファデータ取得 |
| `get_texture_info` | テクスチャメタデータ |
| `get_pipeline_state` | パイプライン状態全体 |

## 通信プロトコル

`[4バイト長さ (big-endian)][JSON]`

## 開発ノート

- RenderDoc拡張機能はPython 3.6標準ライブラリのみ使用
- ReplayControllerへのアクセスは`BlockInvoke`経由で行う
- ソケットは127.0.0.1のみバインド（セキュリティ）

## 参考リンク

- [FastMCP](https://github.com/jlowin/fastmcp)
- [RenderDoc Python API](https://renderdoc.org/docs/python_api/index.html)
- [RenderDoc Extension Registration](https://renderdoc.org/docs/how/how_python_extension.html)
