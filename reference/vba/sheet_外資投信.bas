Attribute VB_Name = "工作表35"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 2, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    '------------110/4/28 下載三大法人買賣超
    SName = "三大法人"
    Application.StatusBar = "開始抓取三大法人買賣超，請稍待..."
    Application.ScreenUpdating = False
'    StartDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A21"), "yyyy-m-d")
'    EndDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A2"), "yyyy-m-d")
    If Range("F1") = "" Then
'        Get_法人持股 Range("B1"), SName, StartDate, EndDate
        Get_法人持股 Range("B1"), SName     '110/5/22改採網址"近20日"選項，而不自己判斷日期
        Get_BASIC_三大法人 Range("B1"), SName       '110/8/19取得股本，以利計算本比、投本比日"
    Else
'        Get_法人持股 Range("F1"), SName, StartDate, EndDate
        Get_法人持股 Range("F1"), SName
        Get_BASIC_三大法人 Range("F1"), SName
    End If
    Application.ScreenUpdating = True
    Application.StatusBar = False
    Range("B1").Select

End Sub
