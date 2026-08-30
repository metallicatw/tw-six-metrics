Attribute VB_Name = "工作表42"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton2, 5, 0, MSForms, CommandButton"
Attribute VB_Control = "CommandButton1, 2, 1, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    SName = "大戶持股Temp"
    theShareHoldType_持股比例 = "%E6%8C%81%E6%9C%89%E6%AF%94%E4%BE%8B%E5%8D%80%E9%96%93%E5%88%86%E7%B4%9A%E4%B8%80%E8%A6%BD(%E5%AE%8C%E6%95%B4)"            '持股比例區間分級一覽(完整)
    theShareHoldType_持股張數 = "%E6%8C%81%E6%9C%89%E5%BC%B5%E6%95%B8%E5%8D%80%E9%96%93%E5%88%86%E7%B4%9A%E4%B8%80%E8%A6%BD(%E5%AE%8C%E6%95%B4)"            '持股張數區間分級一覽(完整)
    theShareHoldType_持股人數 = "%E6%8C%81%E6%9C%89%E4%BA%BA%E6%95%B8%E5%8D%80%E9%96%93%E5%88%86%E7%B4%9A%E4%B8%80%E8%A6%BD(%E5%AE%8C%E6%95%B4)"           '持股人數區間分級一覽(完整)
    theCol_持股比例 = 1
    theCol_持股張數 = 27
    theCol_持股人數 = 53
   
    If Range("F1") = "" Then
        Application.StatusBar = "開始抓取股東持股比例資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("B1"), SName, theShareHoldType_持股比例, theCol_持股比例, Range("M2")
        Application.StatusBar = "開始抓取股東持股張數資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("B1"), SName, theShareHoldType_持股張數, theCol_持股張數, Range("M2")
        Application.StatusBar = "開始抓取股東持股人數資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("B1"), SName, theShareHoldType_持股人數, theCol_持股人數, Range("M2")
    Else
        Application.StatusBar = "開始抓取股東持股比例資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("F1"), SName, theShareHoldType_持股比例, theCol_持股比例, Range("M2")
        Application.StatusBar = "開始抓取股東持股張數資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("F1"), SName, theShareHoldType_持股張數, theCol_持股張數, Range("M2")
        Application.StatusBar = "開始抓取股東持股人數資料，請稍待..."
        Get_data_from_GoodInfo_大戶持股 Range("F1"), SName, theShareHoldType_持股人數, theCol_持股人數, Range("M2")
    End If
    
    Application.StatusBar = False
    Range("B1").Select

End Sub

Private Sub CommandButton2_Click()

    Range("M5") = ""
    Set oShell = CreateObject("WScript.Shell")
    
    AutoConfigURL = "reg query ""HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"" /v AutoConfigURL"
    ProxyEnable = "reg query ""HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"" /v ProxyEnable"
    ProxyServer = "reg query ""HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"" /v ProxyServer"
'    ImportProxy = "netsh winhttp import proxy source=ie"
'    ShowProxy = "netsh winhttp show proxy"
'    ResetProxy = "netsh winhttp reset proxy"
    
'    AutoConfigInfo = Split(Split(CreateObject("wscript.shell").exec(AutoConfigURL).stdout.readall, vbCrLf)(2), "    ")(3)
    AutoConfigInfo = Split(CreateObject("wscript.shell").exec(AutoConfigURL).stdout.readall, vbCrLf)(2)
    If AutoConfigInfo = "" Then
        ProxyEnableInfo = Split(Split(CreateObject("wscript.shell").exec(ProxyEnable).stdout.readall, vbCrLf)(2), "    ")(3)
        If ProxyEnableInfo = "0x0" Then
            Range("M5") = "直接存取 (不使用 Proxy 伺服器)"
        Else
            ProxyServerInfo = Split(Split(CreateObject("wscript.shell").exec(ProxyServer).stdout.readall, vbCrLf)(2), "    ")(3)
            Range("M5") = "使用 Proxy 伺服器存取，Proxy IP：" & ProxyServerInfo
        End If
    Else
        Range("M5") = "目前設定AutoProxy(" & Split(AutoConfigInfo, "    ")(3) & ")，無法取得Proxy IP"
    End If
    Range("B1").Select

End Sub
