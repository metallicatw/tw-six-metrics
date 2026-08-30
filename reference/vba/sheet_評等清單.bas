Attribute VB_Name = "工作表30"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton7, 8, 3, MSForms, CommandButton"
Attribute VB_Control = "CommandButton6, 7, 4, MSForms, CommandButton"
Attribute VB_Control = "CommandButton4, 5, 5, MSForms, CommandButton"
Attribute VB_Control = "CommandButton5, 6, 6, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    Application.Calculation = xlCalculationManual
    Range("E1") = "手動重算"
    Range("B1").Select
    
End Sub

Private Sub CommandButton2_Click()
    
    Application.Calculation = xlCalculationAutomatic
    Range("E1") = "自動重算"
    Range("B1").Select

End Sub

Private Sub CommandButton3_Click()
    
    ActiveSheet.Calculate   '計算工作表，按[手動重算]，就要再按[計算工作表]
    Range("B1").Select
    
End Sub

Private Sub CommandButton4_Click()

    '六大指標評分/評等轉換-->[數字]轉[英文字母]
    RowBgn = 5
    RowEnd = Cells(Rows.Count, "A").End(xlUp).Row
    Application.Calculation = xlCalculationManual
    Application.ScreenUpdating = False   '畫面不會跳動
    For r = RowBgn To RowEnd
        For c = 10 To 146 Step 17
            If Not IsError(Cells(r, c)) Then
                If Cells(r, c) = 4 Then             '營收年增率評等
                    Cells(r, c) = "AA"
                ElseIf Cells(r, c) = 3 Then
                    Cells(r, c) = "A"
                ElseIf Cells(r, c) = 2 Then
                    Cells(r, c) = "BB"
                ElseIf Cells(r, c) = 1 Then
                    Cells(r, c) = "B"
                ElseIf Cells(r, c) = 0 Then
                    Cells(r, c) = "C"
                End If
            End If
            If Not IsError(Cells(r, c + 1)) Then
                If Cells(r, c + 1) = 4 Then         '營業利益率評等
                    Cells(r, c + 1) = "AA"
                ElseIf Cells(r, c + 1) = 3 Then
                    Cells(r, c + 1) = "A"
                ElseIf Cells(r, c + 1) = 2 Then
                    Cells(r, c + 1) = "BB"
                ElseIf Cells(r, c + 1) = 1 Then
                    Cells(r, c + 1) = "B"
                ElseIf Cells(r, c + 1) = 0 Then
                    Cells(r, c + 1) = "C"
                End If
            End If
            If Not IsError(Cells(r, c + 2)) Then
                If Cells(r, c + 2) = 4 Then         '稅後淨利年增率評等
                    Cells(r, c + 2) = "AA"
                ElseIf Cells(r, c + 2) = 3 Then
                    Cells(r, c + 2) = "A"
                ElseIf Cells(r, c + 2) = 2 Then
                    Cells(r, c + 2) = "BB"
                ElseIf Cells(r, c + 2) = 1 Then
                    Cells(r, c + 2) = "B"
                ElseIf Cells(r, c + 2) = 0 Then
                    Cells(r, c + 2) = "C"
                End If
            End If
            If Not IsError(Cells(r, c + 3)) Then
                If Cells(r, c + 3) = 4 Then         '每股盈餘EPS評等
                    Cells(r, c + 3) = "AA"
                ElseIf Cells(r, c + 3) = 3 Then
                    Cells(r, c + 3) = "A"
                ElseIf Cells(r, c + 3) = 2 Then
                    Cells(r, c + 3) = "BB"
                ElseIf Cells(r, c + 3) = 1 Then
                    Cells(r, c + 3) = "B"
                ElseIf Cells(r, c + 3) = 0 Then
                    Cells(r, c + 3) = "C"
                End If
            End If
            If Not IsError(Cells(r, c + 4)) Then
                If Cells(r, c + 4) = 4 Then         '存貨周轉率評等
                    Cells(r, c + 4) = "AA"
                ElseIf Cells(r, c + 4) = 3 Then
                    Cells(r, c + 4) = "A"
                ElseIf Cells(r, c + 4) = 2 Then
                    Cells(r, c + 4) = "BB"
                ElseIf Cells(r, c + 4) = 1 Then
                    Cells(r, c + 4) = "B"
                ElseIf Cells(r, c + 4) = 0 Then
                    Cells(r, c + 4) = "C"
                End If
            End If
            If Not IsError(Cells(r, c + 5)) Then
                If Cells(r, c + 5) = 4 Then         '自由現金流量評等
                    Cells(r, c + 5) = "AA"
                ElseIf Cells(r, c + 5) = 3 Then
                    Cells(r, c + 5) = "A"
                ElseIf Cells(r, c + 5) = 2 Then
                    Cells(r, c + 5) = "BB"
                ElseIf Cells(r, c + 5) = 1 Then
                    Cells(r, c + 5) = "B"
                ElseIf Cells(r, c + 5) = 0 Then
                    Cells(r, c + 5) = "C"
                End If
            End If
        Next c
'        DoEvents
    Next r
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    Range("B1").Select
    MsgBox "完成!"

End Sub

Private Sub CommandButton5_Click()

    '六大指標評分/評等轉換-->[英文字母]轉[數字]
    RowBgn = 5
    RowEnd = Cells(Rows.Count, "A").End(xlUp).Row
    Application.Calculation = xlCalculationManual
    Application.ScreenUpdating = False   '畫面不會跳動
    For r = RowBgn To RowEnd
        For c = 10 To 146 Step 17
            If Not IsError(Cells(r, c)) Then
                If Cells(r, c) = "AA" Then             '營收年增率評等
                    Cells(r, c) = 4
                ElseIf Cells(r, c) = "A" Then
                    Cells(r, c) = 3
                ElseIf Cells(r, c) = "BB" Then
                    Cells(r, c) = 2
                ElseIf Cells(r, c) = "B" Then
                    Cells(r, c) = 1
                ElseIf Cells(r, c) = "C" Then
                    Cells(r, c) = 0
                End If
            End If
            If Not IsError(Cells(r, c + 1)) Then
                If Cells(r, c + 1) = "AA" Then         '營業利益率評等
                    Cells(r, c + 1) = 4
                ElseIf Cells(r, c + 1) = "A" Then
                    Cells(r, c + 1) = 3
                ElseIf Cells(r, c + 1) = "BB" Then
                    Cells(r, c + 1) = 2
                ElseIf Cells(r, c + 1) = "B" Then
                    Cells(r, c + 1) = 1
                ElseIf Cells(r, c + 1) = "C" Then
                    Cells(r, c + 1) = 0
                End If
            End If
            If Not IsError(Cells(r, c + 2)) Then
                If Cells(r, c + 2) = "AA" Then         '稅後淨利年增率評等
                    Cells(r, c + 2) = 4
                ElseIf Cells(r, c + 2) = "A" Then
                    Cells(r, c + 2) = 3
                ElseIf Cells(r, c + 2) = "BB" Then
                    Cells(r, c + 2) = 2
                ElseIf Cells(r, c + 2) = "B" Then
                    Cells(r, c + 2) = 1
                ElseIf Cells(r, c + 2) = "C" Then
                    Cells(r, c + 2) = 0
                End If
            End If
            If Not IsError(Cells(r, c + 3)) Then
                If Cells(r, c + 3) = "AA" Then         '每股盈餘EPS評等
                    Cells(r, c + 3) = 4
                ElseIf Cells(r, c + 3) = "A" Then
                    Cells(r, c + 3) = 3
                ElseIf Cells(r, c + 3) = "BB" Then
                    Cells(r, c + 3) = 2
                ElseIf Cells(r, c + 3) = "B" Then
                    Cells(r, c + 3) = 1
                ElseIf Cells(r, c + 3) = "C" Then
                    Cells(r, c + 3) = 0
                End If
            End If
            If Not IsError(Cells(r, c + 4)) Then
                If Cells(r, c + 4) = "AA" Then         '存貨周轉率評等
                    Cells(r, c + 4) = 4
                ElseIf Cells(r, c + 4) = "A" Then
                    Cells(r, c + 4) = 3
                ElseIf Cells(r, c + 4) = "BB" Then
                    Cells(r, c + 4) = 2
                ElseIf Cells(r, c + 4) = "B" Then
                    Cells(r, c + 4) = 1
                ElseIf Cells(r, c + 4) = "C" Then
                    Cells(r, c + 4) = 0
                End If
            End If
            If Not IsError(Cells(r, c + 5)) Then
                If Cells(r, c + 5) = "AA" Then         '自由現金流量評等
                    Cells(r, c + 5) = 4
                ElseIf Cells(r, c + 5) = "A" Then
                    Cells(r, c + 5) = 3
                ElseIf Cells(r, c + 5) = "BB" Then
                    Cells(r, c + 5) = 2
                ElseIf Cells(r, c + 5) = "B" Then
                    Cells(r, c + 5) = 1
                ElseIf Cells(r, c + 5) = "C" Then
                    Cells(r, c + 5) = 0
                End If
            End If
        Next c
'        DoEvents
    Next r
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    Range("B1").Select
    MsgBox "完成!"

End Sub

Private Sub CommandButton6_Click()

    Union(Range("J:O"), Range("S:X"), Range("AA:AF"), Range("AJ:AO"), _
    Range("AR:AW"), Range("BA:BF"), Range("BI:BN"), Range("BR:BW"), _
    Range("BZ:CE"), Range("CI:CN"), Range("CQ:CV"), Range("CZ:DE"), _
    Range("DH:DM"), Range("DQ:DV"), Range("DY:ED"), Range("EH:EM"), _
    Range("EP:EU"), Range("EY:FD")).EntireColumn.Hidden = False
    Range("B1").Select

End Sub

Private Sub CommandButton7_Click()

    Union(Range("J:O"), Range("S:X"), Range("AA:AF"), Range("AJ:AO"), _
    Range("AR:AW"), Range("BA:BF"), Range("BI:BN"), Range("BR:BW"), _
    Range("BZ:CE"), Range("CI:CN"), Range("CQ:CV"), Range("CZ:DE"), _
    Range("DH:DM"), Range("DQ:DV"), Range("DY:ED"), Range("EH:EM"), _
    Range("EP:EU"), Range("EY:FD")).EntireColumn.Hidden = True
    Range("B1").Select
    
End Sub

Private Sub Worksheet_BeforeDoubleClick(ByVal Target As Range, Cancel As Boolean)

    Col = ActiveCell.Column
    Row = ActiveCell.Row
    EndRow = Cells(Rows.Count, "A").End(xlUp).Row
    If Col = 1 And Row >= 5 And Row <= EndRow Then
        Sheets("評價簡表").Activate
        Sheets("評價簡表").Select
        Sheets("評價簡表").Range("B1") = Target.Value
    End If

End Sub
