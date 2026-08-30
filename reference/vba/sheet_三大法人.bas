Attribute VB_Name = "工作表34"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 3, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

'    StartDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A21"), "yyyy-m-d")
'    EndDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A2"), "yyyy-m-d")
    Application.StatusBar = "開始抓取三大法人持股資料，請稍待..."
    If Range("G1") = "" Then
'        Get_法人持股 Range("B1"), "三大法人", StartDate, EndDate
        Get_法人持股 Range("B1"), "三大法人"    '110/11/21，5/22沒改到，補修正，110/5/22改採網址"近20日"選項，而不自己判斷日期
    Else
'        Get_法人持股 Range("G1"), "三大法人", StartDate, EndDate
        Get_法人持股 Range("G1"), "三大法人"    '110/11/21，5/22沒改到，補修正，110/5/22改採網址"近20日"選項，而不自己判斷日期
    End If
    Range("B1").Select
    Application.StatusBar = False

End Sub
