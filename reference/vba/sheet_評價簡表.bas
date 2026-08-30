Attribute VB_Name = "工作表22"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 12, 0, MSForms, CommandButton"
Attribute VB_Control = "CommandButton2, 13, 1, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    If Range("M19") = "" Then
        Range("M19") = Left(Sheets("ISQ").Range("B5"), 4) - 1911
    End If
    theURL = "https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id=" & Range("B1") & "&year=" & Range("M19") & "&mtype=F&"
    ThisWorkbook.FollowHyperlink (theURL)      '開啟公開資訊觀測站股東會年報網頁
    Range("B1").Select
    
End Sub

Private Sub CommandButton2_Click()

    If Range("M19") = "" Then
        Range("M19") = Left(Sheets("ISQ").Range("B5"), 4) - 1911
    End If
    theURL = "https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id=" & Range("B1") & "&year=" & Range("M19") & "&seamon=&mtype=A&"
    ThisWorkbook.FollowHyperlink (theURL)      '開啟公開資訊觀測站財務報告書網頁
    Range("B1").Select
    
End Sub

Private Sub Worksheet_Change(ByVal Target As Range)

    If Target.Address = "$B$1" Then     '109/03/23
'        CFQ_StockNo = CInt(Right(Left(Sheets("CFQ").Range("A3"), Len(Sheets("CFQ").Range("A3")) - 6), 4))
'        FRQ_StockNo = CInt(Right(Left(Sheets("FRQ").Range("A3"), Len(Sheets("FRQ").Range("A3")) - 6), 4))
'        ISQ_StockNo = CInt(Right(Left(Sheets("ISQ").Range("A3"), Len(Sheets("ISQ").Range("A3")) - 6), 4))
'        BSQ_StockNo = CInt(Right(Left(Sheets("BSQ").Range("A3"), Len(Sheets("BSQ").Range("A3")) - 6), 4))
'        營收_StockNo = CInt(Right(Left(Sheets("營收").Range("A3"), Len(Sheets("營收").Range("A3")) - 9), 4))
'        BASIC_StockNo = CInt(Right(Left(Sheets("BASIC").Range("A3"), Len(Sheets("BASIC").Range("A3")) - 9), 4))
'        Do While Sheets("評價簡表").Range("B1") <> CFQ_StockNo And Sheets("評價簡表").Range("B1") <> FRQ_StockNo And Sheets("評價簡表").Range("B1") <> ISQ_StockNo And Sheets("評價簡表").Range("B1") <> BSQ_StockNo And Sheets("評價簡表").Range("B1") <> 營收_StockNo And Sheets("評價簡表").Range("B1") <> BASIC_StockNo
'            DoEvents
'        Loop
        tt = Timer      '109/03/26 計算查詢秒數
        Range("M1") = 0
        Range("M14:M15") = 0
        Range("N7:N16") = ""    '109/04/07
        Application.Calculation = xlCalculationManual
        Application.EnableEvents = False
        Application.ScreenUpdating = False   '畫面不會跳動
        
        Application.StatusBar = "開始抓取財務比率表，請稍待..."
        t0 = Timer
        Get_FRQ Target.Value, "FRQ"
        Range("N7") = WorksheetFunction.Round(Timer - t0, 2)
        Application.StatusBar = "開始抓取現金流量表，請稍待..."
        t0 = Timer
        Get_CFQ Target.Value, "CFQ"
        Range("N8") = WorksheetFunction.Round(Timer - t0, 2)
        Application.StatusBar = "開始抓取綜合損益表，請稍待..."
        t0 = Timer
        Get_ISQ Target.Value, "ISQ"
        Range("N9") = WorksheetFunction.Round(Timer - t0, 2)
        Application.StatusBar = "開始抓取資產負債表，請稍待..."
        t0 = Timer
        Get_BSQ Target.Value, "BSQ"
        Range("N10") = WorksheetFunction.Round(Timer - t0, 2)
        Application.StatusBar = "開始抓取基本資料，請稍待..."
        t0 = Timer
        Get_BASIC Target.Value, "BASIC"
        Range("N12") = WorksheetFunction.Round(Timer - t0, 2)
        Application.StatusBar = "開始抓取月營收，請稍待..."
        t0 = Timer
        Get_REV Target.Value, "營收"
        Range("N13") = WorksheetFunction.Round(Timer - t0, 2)
        
        If (Sheets("設定").Range("G2") = "Y") Then
            Application.StatusBar = "開始抓取經營績效，請稍待..."
            t0 = Timer
            Get_OPQ Target.Value, "OPQ"
            Range("N14") = WorksheetFunction.Round(Timer - t0, 2)
            If Sheets("EPQ").Range("A3") <> "" Then
                Range("M14") = 1
            End If
            Application.StatusBar = "開始抓取獲利能力，請稍待..."
            t0 = Timer
            Get_EPQ Target.Value, "EPQ"
            Range("N15") = WorksheetFunction.Round(Timer - t0, 2)
            If Sheets("EPQ").Range("A3") <> "" Then
                Range("M15") = 1
            End If
        End If
        Application.StatusBar = "開始抓股利，請稍待..."
        t0 = Timer
        Get_股利 Target.Value, "股利"
        Range("N16") = WorksheetFunction.Round(Timer - t0, 2)

        Application.ScreenUpdating = True
        Application.EnableEvents = True
        Application.Calculation = xlCalculationAutomatic
        Application.StatusBar = False
        Range("M1") = WorksheetFunction.Round(Timer - tt, 2)
        Range("B1").Select
    End If

End Sub

