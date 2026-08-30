Attribute VB_Name = "工作表39"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 3, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    Application.StatusBar = "開始抓取富聯網個股新聞，請稍待..."
    
    If Range("D1") = "" Then
        Get_StockNews_from_MoneyLink Range("B1"), "個股新聞"
    Else
        Get_StockNews_from_MoneyLink Range("D1"), "個股新聞"
    End If
    lastrow = Range("A4").End(xlDown).Row
    Range("A" & lastrow + 1) = "以上個股新聞為富聯網彙整提供，共 " & lastrow - 3 & " 筆"
    Application.StatusBar = "開始抓取Yahoo個股新聞，請稍待..."
    If Range("D1") = "" Then
        Get_StockNews_from_Yahoo Range("B1"), "個股新聞"
    Else
        Get_StockNews_from_Yahoo Range("D1"), "個股新聞"
    End If
    lastrow2 = Range("A4").End(xlDown).Row
    Range("A" & lastrow2 + 1) = "以上個股新聞為Yahoo彙整提供，共 " & lastrow2 - lastrow - 1 & " 筆"
    
    Application.StatusBar = False
    Range("B1").Select

End Sub
