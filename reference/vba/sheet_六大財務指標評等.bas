Attribute VB_Name = "工作表28"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CheckBox1, 123, 0, MSForms, CheckBox"
Attribute VB_Control = "CommandButton2, 13, 1, MSForms, CommandButton"
Attribute VB_Control = "CommandButton1, 11, 2, MSForms, CommandButton"
Private Sub CheckBox1_Click()

    Dim i6_1Cht As ChartObject
    Dim i6_2Cht As ChartObject
    Dim i6_3Cht As ChartObject
    Dim i6_4Cht As ChartObject
    Dim i6_5Cht As ChartObject
    Dim i6_6Cht As ChartObject
    Set i6_1Cht = Me.ChartObjects("近6月營收年增率")
    i6_1Cht.Visible = CheckBox1.Value
    Set i6_2Cht = Me.ChartObjects("近6季營業利益率")
    i6_2Cht.Visible = CheckBox1.Value
    Set i6_3Cht = Me.ChartObjects("近6季稅後淨利年增率")
    i6_3Cht.Visible = CheckBox1.Value
    Set i6_4Cht = Me.ChartObjects("近6季每股盈餘EPS")
    i6_4Cht.Visible = CheckBox1.Value
    Set i6_5Cht = Me.ChartObjects("近6季存貨周轉率")
    i6_5Cht.Visible = CheckBox1.Value
    Set i6_6Cht = Me.ChartObjects("近6季自由現金流量")
    i6_6Cht.Visible = CheckBox1.Value

End Sub

Private Sub CommandButton1_Click()

    If Sheets("EPS預估與估價").Range("B2") = "" Then
        Call Output2word("設定")
        MsgBox "報表已產出！"
    Else
        MsgBox "請先更新「預估EPS」!", vbOKOnly + vbInformation, "資料不一致"
    End If
    
    Application.ScreenUpdating = False
    With Sheets("獲利季節性")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A1").Select
    End With
    With Sheets("營收季節性")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A1").Select
    End With
    With Sheets("河流圖")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A1").Select
    End With
    With Sheets("EPS預估3")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A2").Select
    End With
    With Sheets("EPS預估2")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A2").Select
    End With
    With Sheets("EPS預估與估價")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A1").Select
    End With
    With Sheets("評價簡表")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("B1").Select
    End With
    With Sheets("六大財務指標評等")
        .Select
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
        .Range("A1").Select
    End With
    Application.ScreenUpdating = True

End Sub

Private Sub CommandButton2_Click()

    '109/03/23--------------Begin
    Application.Calculation = xlCalculationManual
    Application.ScreenUpdating = False   '畫面不會跳動
    Application.StatusBar = "開始抓取財務比率表，請稍待..."
    Get_FRQ Range("B1"), "FRQ"
    Application.StatusBar = "開始抓取現金流量表，請稍待..."
    Get_CFQ Range("B1"), "CFQ"
    Application.StatusBar = "開始抓取綜合損益表，請稍待..."
    Get_ISQ Range("B1"), "ISQ"
    Application.StatusBar = "開始抓取資產負債表，請稍待..."
    Get_BSQ Range("B1"), "BSQ"
    Application.StatusBar = "開始抓取基本資料，請稍待..."
    Get_BASIC Range("B1"), "BASIC"
    Application.StatusBar = "開始抓取月營收，請稍待..."
    Get_REV Range("B1"), "營收"

    If (Sheets("設定").Range("G2") = "Y") Then
        Application.StatusBar = "開始抓取經營績效，請稍待..."
        Get_OPQ Range("B1"), "OPQ"
        Application.StatusBar = "開始抓取獲利能力，請稍待..."
        Get_EPQ Range("B1"), "EPQ"
    End If
    Application.StatusBar = "開始抓取股利，請稍待..."
    Get_股利 Range("B1"), "股利"
    
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    Application.StatusBar = False
    '109/03/23--------------End

'    ActiveWorkbook.RefreshAll
    Range("A1").Select
    
End Sub
