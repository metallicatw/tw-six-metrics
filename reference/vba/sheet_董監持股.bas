Attribute VB_Name = "工作表40"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 1, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    SName = "董監持股Temp"
   
    Application.StatusBar = "開始抓取董監事持股資料及資料欄位轉換處理，請稍待..."
    If Range("F1") = "" Then
        Get_data_from_GoodInfo_董監持股 Range("B1"), SName
    Else
        Get_data_from_GoodInfo_董監持股 Range("F1"), SName
    End If
    
    Application.StatusBar = False
    Range("B1").Select

End Sub
