# 维护与发布

仓库：https://github.com/wanghaoran1016-commits/philips-water-ha

1. 保留 LICENSE、NOTICE.md 与 UPSTREAM_COMMIT。
2. 发布前运行离线测试，核对 README 的已验证范围，检查提交不包含账号、设备诊断或抓包。
3. GitHub Releases → Draft a new release；标签建议 v0.2.0b8，目标为已验证的提交；勾选 Set as a pre-release。
4. 发布说明见 RELEASE_NOTES.md；自动生成的 Source code ZIP 可用于手动安装。
5. 未完成的实机测试必须继续写明，不能以 CI 成功替代设备验证。
6. 论坛正文草稿见 FORUM_POST.md，发布前核对仓库链接与实际版本。

HACS 默认商店收录、自动更新和安装流程均未验证，不承诺已支持。
