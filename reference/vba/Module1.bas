Attribute VB_Name = "Module1"
''''''日盛證券 http://jsjustweb.jihsun.com.tw    只能http, 112/11/24 無法使用
''''''國泰世華 https://dj.mybank.com.tw 只能https    110/11/20, 112/11/24 無法使用
''''''玉山證券 sjmain.esunsec.com.tw 110/11/24 無法使用
'凱基證券 https://kgieworld.moneydj.com  http/https皆可, 110/12/25 https
'富邦證券 https://fubon-ebrokerdj.fbs.com.tw  原只能https     110/11/20 http/https皆可
'第一金證券 https://stocks.firstsec.com.tw  只能https   112/6/9 新增, 原為stocks.ftsi.com.tw 只能http
'華南永昌證券 https://just2.entrust.com.tw   112/11/25 https，http/https皆可  109/9/12 新增，取代玉山證券, 110/12/25 https
'永豐金證券 https://stockchannelnew.sinotrade.com.tw    '110/11/21 更新網址，http/https皆可，原為stockchannel.sinotrade.com.tw，只能http
'元富證券 https://newjust.masterlink.com.tw  http/https皆可, 110/12/25 https
'國泰證券 https://djinfo.cathaysec.com.tw   http/https皆可, 110/12/25 https
'元大證券 https://jdata.yuanta.com.tw   112/11/25 新增 http/https皆可
'群益證券 https://stock.capital.com.tw  112/11/25 新增 https
'統一證券 https://pscnetsecrwd.moneydj.com 112/11/25 新增 https
'兆豐證券 https://moneydj.emega.com.tw 112/11/25 新增 https
'合庫證券 https://tcfhcsec.moneydj.com  112/11/25 新增 https

Public Function GetHost() As Variant

    GetHost = Array( _
    "https://moneydj.emega.com.tw", _
    "https://kgieworld.moneydj.com", _
    "https://fubon-ebrokerdj.fbs.com.tw", _
    "https://stocks.firstsec.com.tw", _
    "https://just2.entrust.com.tw", _
    "https://stockchannelnew.sinotrade.com.tw", _
    "https://newjust.masterlink.com.tw", _
    "https://djinfo.cathaysec.com.tw")

End Function
   
Sub WebQuery_HIS_STOCK_PRICE(StockNo, sDate)
    
    Dim URL As String
    
    With Sheets("股價(日)")
         .Visible = True
         .Range("A1:J1000").ClearContents
         '.Activate
    End With
    
    URL = "https://www.cnyes.com/twstock/ps_historyprice.aspx?code=" & StockNo
       
    thePOST = "__VIEWSTATEGENERATOR=7B0F6FE1&__EVENTVALIDATION=/wEWBALarvOrAwKBrZazBAK2os6sDQKI+IfFCXYYGOr3GBowkdYlRqIAgMAA2wdv&pageTypeHidden=1&code=" & StockNo & "&ctl00$ContentPlaceHolder1$startText=" & sDate
    
    With Sheets("股價(日)").QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets("股價(日)").Range("A1"))
        .Name = "HIS_STOCK_PRICE"
        .PostText = thePOST
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = True
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "1"                          '僅抓第1個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
       
End Sub

Sub Get_data_from_GoodInfo_財務比率(StockNo, SName)
    '抓年財務比率(每股稅後盈餘及每股淨值)
    
    Dim arrData(1 To 160, 1 To 16)
    Dim IE As InternetExplorer
'    Set IE = New InternetExplorer
    Set IE = CreateObject("InternetExplorer.Application")       '109/3/9 修正Win10 64bit + Excel 2016 64bit發生Automation Error
    
'    Dim HTMLDoc As HTMLDocument           '108.09.24避免執行到Set HTMLDoc = .document，出現"錯誤13  型態不符合"之異常對話框
    
    Set tmpSName = Sheets(SName)
    
    With tmpSName
        .Visible = True
        .Range("A1:M200").ClearContents
        '.Activate
    End With

    theURL = "https://goodinfo.tw/StockInfo/StockFinDetail.asp?RPT_CAT=XX_M_QUAR_ACC&STOCK_ID=" & StockNo
    'theURL = "https://goodinfo.tw/StockInfo/StockFinDetail.asp?RPT_CAT=XX_M_QUAR_ACC&STOCK_ID=2330"

    With IE
        .Visible = False
        .navigate theURL
        
      
        Do While .Busy Or .readyState <> READYSTATE_COMPLETE: DoEvents: Loop
        Set HTMLDoc = .document
        Set RPT_CAT = HTMLDoc.getElementById("RPT_CAT")
        RPT_CAT.selectedIndex = 2   '0:合併報表 – 單季; 1:合併報表 – 累季; 2:合併報表 – 年度; 3:合併報表 – 近四季
        RPT_CAT.FireEvent ("onchange")
        Application.Wait (Now + TimeValue("00:00:03"))
'        Do While .Busy Or .readyState <> READYSTATE_COMPLETE: DoEvents: Loop
        Set tables = HTMLDoc.getElementsByTagName("table")
        wr = 1
        For Each Table In tables
            If Table.innerText Like "*獲利能力*" Then
                For Each theRow In Table.Rows
                    wc = 1
                    For Each theCell In theRow.Cells
                        'tmpSName.Cells(wr, wc) = theCell.innerText
                        arrData(wr, wc) = theCell.innerText
                        wc = wc + 1
                    Next
                    wr = wr + 1
                    'tmpSName.Cells(wr, "A").Activate
                Next
            End If
        Next
    End With
    IE.Quit
    Set IE = Nothing
    
'    Application.ScreenUpdating = False   '畫面不會跳動
    
    Sheets(SName).Select
    Range("A1").Resize(wr, wc) = arrData
    Range("A1").EntireRow.Delete
    Sheets("EPS預估與估價").Select

End Sub

Sub Get_data_from_MoneyDJ_年財務比率(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        .Range("A2:J200").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zcr/zcr0.djhtm?b=Y&a=" & StockNo
    Else
        URL = "https://kgieworld.moneydj.com/z/zc/zcr/zcr0.djhtm?b=Y&a=" & StockNo
    End If
    
    MoneyDJ_財務比率_New URL, SName
    
'    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
'        .Name = "MoneyDJ_年財務比率"
'        .FieldNames = True
'        .RowNumbers = False
'        .FillAdjacentFormulas = False
'        .PreserveFormatting = False
'        .RefreshOnFileOpen = False
'        .BackgroundQuery = True
''        .RefreshStyle = xlInsertDeleteCells
'        .RefreshStyle = xlOverwriteCells
'        .SavePassword = False
'        .SaveData = False
'        .AdjustColumnWidth = False
'        .RefreshPeriod = 0
'        .WebSelectionType = xlSpecifiedTables
'        .WebFormatting = xlWebFormattingNone
'        .WebTables = "1"                        '僅抓第1個表格
'        .WebPreFormattedTextToColumns = True
'        .WebConsecutiveDelimitersAsOne = True
'        .WebSingleBlockTextImport = False
'        .WebDisableDateRecognition = True         '關閉日期辨識
'        .Refresh BackgroundQuery:=False
'        .Delete
'    End With
    
End Sub

Sub MoneyDJ_TW_PRICE_New(SName, StockNo, theInterval)
      
    Dim arrData(1440, 1 To 7)
   
   '定義變數
    Dim XMLHTTP As Variant
    Dim Result As Variant
    Dim theDate As Variant
    Dim theValue(1 To 20) As Variant
    Dim theURL As Variant
    
    With Sheets(SName)
        .Range("S:Y").Cells.ClearContents
        If SName = "股價(週)" Then      '112/11/28 修正[EPS預估與估價]之股價(週)及股價(日)2之證券商的判斷條件
            theCORP = GetHost(.Range("Z3"))      '109/05/02 可選擇不同券商
        Else
            theCORP = GetHost(.Range("F1"))
        End If
    End With
   
   '採用MoneyDJ標準化財報資訊系統的券商
    'theCORP = "jsjustweb.jihsun.com.tw"
'    theCORP = "fubon-ebrokerdj.fbs.com.tw"
   
   '判斷資料頻率
    Select Case theInterval
        Case "D": K_TYPE = "D"
        Case "W": K_TYPE = "W"
        Case "M": K_TYPE = "M"
        Case "A": K_TYPE = "A"
        Case Else: K_TYPE = "D"
    End Select
    
   '以 Late binding 建立物件
    Set XMLHTTP = CreateObject("MSXML2.XMLHTTP.6.0")
    theURL = theCORP & "/Z/ZC/ZCW/CZKC1_" & StockNo & "_" & K_TYPE & "_1440.djbcd"
   '採用XMLHTTP OBJECT
    With XMLHTTP
        .Open "GET", theURL, False
        .send
    End With
     While XMLHTTP.Status <> 200 Or XMLHTTP.readyState <> 4
        DoEvents
    Wend
    
    Result = Split(XMLHTTP.responseText, " ")
    
    theDate = Split(Result(0), ",")       '日期
    theValue(1) = Split(Result(1), ",")   '開盤
    theValue(2) = Split(Result(2), ",")   '最高
    theValue(3) = Split(Result(3), ",")   '最低
    theValue(4) = Split(Result(4), ",")   '收盤
    theValue(5) = Split(Result(5), ",")   '成交量
        
   '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual     '109/03/29
        .ScreenUpdating = False
    End With
    
    With Sheets(SName)
'        .Activate
    arrData(0, 1) = "年度"
    arrData(0, 2) = "日期"
    arrData(0, 3) = "開盤"
    arrData(0, 4) = "最高"
    arrData(0, 5) = "最低"
    arrData(0, 6) = "收盤"
    arrData(0, 7) = "成交量"

        For i = 0 To UBound(theDate)
            '西元日期 2014/01/10
             If Len(theDate(i)) = 10 Then
               arrData(i + 1, 2) = theDate(i)
            '民國日期 1030110 or 981023
             Else
                theYY = IIf(Len(theDate(i)) = 6, Left(theDate(i), 2), Left(theDate(i), 3)) + 1911
                theMM = Left(Right(theDate(i), 4), 2)
                theDD = Right(theDate(i), 2)
               arrData(i + 1, 2) = DateSerial(theYY, theMM, theDD)
             End If
            arrData(i + 1, 1) = Year(arrData(i + 1, 2))
                        
            '寫入開、高、低、收、量
             For c = 1 To 5
                arrData(i + 1, c + 2) = theValue(c)(i)
             Next c
        Next
        .Range("S1").Resize(1441, 7) = arrData
        最後一筆 = .Cells(Rows.Count, "T").End(xlUp).Row
       .Range("T2:T" & 最後一筆).NumberFormatLocal = "yyyy-mm-dd"
       .Range("U2:X" & 最後一筆).NumberFormatLocal = "0.0_ "
       .Range("Y2:Y" & 最後一筆).NumberFormatLocal = "#,##0_ "
       .Columns("S:Y").AutoFit
       .Range("U:X").ColumnWidth = 6
       .Range("Y:Y").ColumnWidth = 8
       
    End With
    
   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic      '109/03/29
        .ScreenUpdating = True
    End With
    
End Sub

Sub MoneyDJ_TW_PRICE(SName, StockNo, theInterval)
      
   '定義變數
    Dim XMLHTTP As Variant
    Dim Result As Variant
    Dim theDate As Variant
    Dim theValue(1 To 20) As Variant
    Dim theURL As Variant
    
    With Sheets(SName)
        .Range("S:Y").Cells.ClearContents
        theCORP = GetHost(.Range("Z3"))      '109/05/02 可選擇不同券商
    End With
   
   '採用MoneyDJ標準化財報資訊系統的券商
    'theCORP = "jsjustweb.jihsun.com.tw"
    'theCORP = "fubon-ebrokerdj.fbs.com.tw"
   
   '判斷資料頻率
    Select Case theInterval
        Case "D": K_TYPE = "D"
        Case "W": K_TYPE = "W"
        Case "M": K_TYPE = "M"
        Case "A": K_TYPE = "A"
        Case Else: K_TYPE = "D"
    End Select
    
   '以 Late binding 建立物件
    Set XMLHTTP = CreateObject("MSXML2.XMLHTTP.6.0")
    theURL = theCORP & "/Z/ZC/ZCW/CZKC1_" & StockNo & "_" & K_TYPE & "_1440.djbcd"
   '採用XMLHTTP OBJECT
    With XMLHTTP
        .Open "GET", theURL, False
        .send
    End With
     While XMLHTTP.Status <> 200 Or XMLHTTP.readyState <> 4
        DoEvents
    Wend
    
    Result = Split(XMLHTTP.responseText, " ")
    
    theDate = Split(Result(0), ",")       '日期
    theValue(1) = Split(Result(1), ",")   '開盤
    theValue(2) = Split(Result(2), ",")   '最高
    theValue(3) = Split(Result(3), ",")   '最低
    theValue(4) = Split(Result(4), ",")   '收盤
    theValue(5) = Split(Result(5), ",")   '成交量
        
   '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual     '109/03/29
        .ScreenUpdating = False
    End With
    
    With Sheets(SName)
'        .Activate
        .Cells(1, "S").Value = "年度"
        .Cells(1, "T").Value = "日期"
        .Cells(1, "U").Value = "開盤"
        .Cells(1, "V").Value = "最高"
        .Cells(1, "W").Value = "最低"
        .Cells(1, "X").Value = "收盤"
        .Cells(1, "Y").Value = "成交量"

        For i = 0 To UBound(theDate)
            '西元日期 2014/01/10
             If Len(theDate(i)) = 10 Then
               .Cells(i + 2, "T").Value = theDate(i)
            '民國日期 1030110 or 981023
             Else
                theYY = IIf(Len(theDate(i)) = 6, Left(theDate(i), 2), Left(theDate(i), 3)) + 1911
                theMM = Left(Right(theDate(i), 4), 2)
                theDD = Right(theDate(i), 2)
               .Cells(i + 2, "T").Value = DateSerial(theYY, theMM, theDD)
             End If
            .Cells(i + 2, "S").Value = Year(.Cells(i + 2, "T").Value)
                        
            '寫入開、高、低、收、量
             For c = 1 To 5
                .Cells(i + 2, c + 20).Value = theValue(c)(i)
             Next c
        Next
        最後一筆 = .Cells(Rows.Count, "T").End(xlUp).Row
       .Range("T2:T" & 最後一筆).NumberFormatLocal = "yyyy-mm-dd"
       .Range("U2:X" & 最後一筆).NumberFormatLocal = "0.0_ "
       .Range("Y2:Y" & 最後一筆).NumberFormatLocal = "#,##0_ "
       .Columns("S:Y").AutoFit
       .Range("U:X").ColumnWidth = 6
       .Range("Y:Y").ColumnWidth = 8
       
    End With
    
   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic      '109/03/29
        .ScreenUpdating = True
    End With
    
End Sub

Sub 計算EPS_BPS(SName, SName_M, SName_G)
    
   '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual     '109/03/29
        .ScreenUpdating = False
    End With
    
    'col_M = Sheets(SName_M).Cells(7, Columns.Count).End(xlToLeft).Column
'    Years_M = Sheets(SName_M).Range("B7").End(xlToRight).Column - 2         'MoneyDJ年財務比率提供多少年
    Years_M = Sheets(SName_M).Range("A6").End(xlToRight).Column - 1         '110/12/25
    Years_G = Sheets(SName_G).Range("A1").End(xlToRight).Column - 1           'Goodinfo年財務比率提供多少年
    If Years_G > 8 Then
        Years_G = 8
    End If
'    Year_M = Sheets(SName_M).Range("C7") - Years_M + 1          '第N年度
    Year_M = Sheets(SName_M).Range("B6") - Years_M + 1          '110/12/25
    Year_G = Sheets(SName_G).Range("B1") - Years_G + 1              '第N年度
    If Years_M >= Years_G Then
        endYears = Years_M
    Else
        endYears = Years_G
    End If
'    Year_fsBgn = Sheets(SName_M).Range("C7")
    Year_fsBgn = Sheets(SName_M).Range("B6")            '110/12/25
    Year_fsEnd = Year_fsBgn - 7
    
    With Sheets(SName)
        For i = 2 To 9      '計算[股價(週)]年度，以第8年度到財報最新年度，如2011~2018
            .Range("L" & i) = Year_fsEnd + i - 2
            .Range("AL" & i) = Year_fsEnd + i - 2
        Next i
        If Year_M <= Year_G Then
            YearEnd = Year_M
        Else
            YearEnd = Year_G
        End If
    
        YearEnd_Row = WorksheetFunction.Match(YearEnd, .Range("L:L"), 0)
        For i = 2 To YearEnd_Row - 1    '計算未滿8年淨值及EPS(=N/A)
            .Range("M" & i) = "N/A"
            .Range("AM" & i) = "N/A"
        Next i

        For i = YearEnd_Row To 9        '從有財報最早年度到最新年度淨值及EPS
'            MoneyDJ每股淨值 = WorksheetFunction.VLookup("每股淨值*", Sheets(SName_M).Range("B:J"), 9 - i + 2, False)
            MoneyDJ每股淨值 = WorksheetFunction.VLookup("每股淨值*", Sheets(SName_M).Range("A:I"), 9 - i + 2, False)            '110/12/25
            Goodinfo每股淨值 = WorksheetFunction.VLookup("每股淨值*", Sheets(SName_G).Range("A:I"), 9 - i + 2, False)
            If MoneyDJ每股淨值 <> "" And MoneyDJ每股淨值 <> "N/A" Then
                .Range("M" & i) = MoneyDJ每股淨值
            ElseIf Goodinfo每股淨值 <> "" And Goodinfo每股淨值 <> "-" Then
                .Range("M" & i) = Goodinfo每股淨值
            Else
                .Range("M" & i) = MoneyDJ每股淨值
            End If
            
'            MoneyDJ每股盈餘 = WorksheetFunction.VLookup("每股盈餘*", Sheets(SName_M).Range("B:J"), 9 - i + 2, False)
            MoneyDJ每股盈餘 = WorksheetFunction.VLookup("每股盈餘*", Sheets(SName_M).Range("A:I"), 9 - i + 2, False)            '110/12/25
            Goodinfo每股盈餘 = WorksheetFunction.VLookup("每股稅後盈餘*", Sheets(SName_G).Range("A:I"), 9 - i + 2, False)
            If MoneyDJ每股盈餘 <> "" And MoneyDJ每股盈餘 <> "N/A" Then
                .Range("AM" & i) = MoneyDJ每股盈餘
            ElseIf Goodinfo每股盈餘 <> "" And Goodinfo每股盈餘 <> "-" Then
                .Range("AM" & i) = Goodinfo每股盈餘
            Else
                .Range("AM" & i) = MoneyDJ每股盈餘
            End If
        Next i
    End With

   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic      '109/03/29
        .ScreenUpdating = True
    End With

End Sub

Sub 計算EPS_BPS2(SName, SName_M)
    
   '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual     '109/03/29
        .ScreenUpdating = False
    End With
    
    'col_M = Sheets(SName_M).Cells(7, Columns.Count).End(xlToLeft).Column
'    Years_M = Sheets(SName_M).Range("B7").End(xlToRight).Column - 2         'MoneyDJ年財務比率提供多少年
'    Year_M = Sheets(SName_M).Range("C7") - Years_M + 1          '第N年度
    Years_M = Sheets(SName_M).Range("A6").End(xlToRight).Column - 1         '110/12/25
    Year_M = Sheets(SName_M).Range("B6") - Years_M + 1          '110/12/25
     endYears = Years_M
'    Year_fsBgn = Sheets(SName_M).Range("C7")        '最新年度
    Year_fsBgn = Sheets(SName_M).Range("B6")        '110/12/25
    Year_fsEnd = Year_fsBgn - 7                                         '第8年度
    
    With Sheets(SName)
        For i = 2 To 9      '計算[股價(週)]年度，以第8年度到財報最新年度，如2011~2018
            .Range("L" & i) = Year_fsEnd + i - 2
            .Range("AL" & i) = Year_fsEnd + i - 2
        Next i
        YearEnd = Year_M
    
        YearEnd_Row = WorksheetFunction.Match(YearEnd, .Range("L:L"), 0)
        For i = 2 To YearEnd_Row - 1    '計算未滿8年淨值及EPS(=N/A)
            .Range("M" & i) = "N/A"
            .Range("AM" & i) = "N/A"
        Next i

        For i = YearEnd_Row To 9        '從有財報最早年度到最新年度淨值及EPS
'            MoneyDJ每股淨值 = WorksheetFunction.VLookup("每股淨值*", Sheets(SName_M).Range("B:J"), 9 - i + 2, False)
            MoneyDJ每股淨值 = WorksheetFunction.VLookup("每股淨值*", Sheets(SName_M).Range("A:I"), 9 - i + 2, False)            '110/12/25
            .Range("M" & i) = MoneyDJ每股淨值
'            MoneyDJ每股盈餘 = WorksheetFunction.VLookup("每股盈餘*", Sheets(SName_M).Range("B:J"), 9 - i + 2, False)
            MoneyDJ每股盈餘 = WorksheetFunction.VLookup("每股盈餘*", Sheets(SName_M).Range("A:I"), 9 - i + 2, False)            '110/12/25
            .Range("AM" & i) = MoneyDJ每股盈餘
        Next i
    End With
    
   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic      '109/03/29
        .ScreenUpdating = True
    End With

End Sub

Sub 計算河流圖股價(SName, YearBgn)
    
    Application.EnableEvents = False
   '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual     '109/03/29
        .ScreenUpdating = False
    End With
    
    Sheets("河流圖").Range("A2") = "Starting"
    With Sheets(SName)
        If YearBgn < .Range("S2") Then
            YearBgn = .Range("S2")
        End If
'        YearEnd = Sheets("MoneyDJ年財務比率").Range("C7")
        YearEnd = Sheets("MoneyDJ年財務比率").Range("B6")           '110/12/25
'        Num = YearEnd - YearBgn - 1     '110/4/1
        Num = YearEnd - YearBgn
        If Num <= 0 Then     '110/4/1例外處理[河流圖]->啟始年度[J3]無法選擇的問題
            Num = 1
        End If
        Sheets("河流圖").Range("P2:P7").Cells.ClearContents
        For i = 1 To Num
            Sheets("河流圖").Range("P" & i + 1) = YearBgn + i
        Next i
        Sheets("河流圖").ComboBox1.ListFillRange = "P2:P" & i
        Sheets("河流圖").ComboBox1.ListIndex = 0
        
        .Range("A2:C1000").Cells.ClearContents
        .Range("AA2:AC1000").Cells.ClearContents
        RowBgn = WorksheetFunction.Match(YearBgn, .Range("S:S"), 1)
        RowEnd = .Range("S1").End(xlDown).Row
        .Range("S" & RowBgn & ":T" & RowEnd).Copy Destination:=.Range("A2")         '年度、日期
        .Range("X" & RowBgn & ":X" & RowEnd).Copy Destination:=.Range("C2")         '收盤價
        .Range("S" & RowBgn & ":T" & RowEnd).Copy Destination:=.Range("AA2")         '年度、日期
        .Range("X" & RowBgn & ":X" & RowEnd).Copy Destination:=.Range("AC2")         '收盤價
    End With
'    Sheets("河流圖").Range("A2") = ""  '113/06/12-->(1)
    
   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic      '109/03/29，113/06/12 執行完該指令-->(2)，會轉跳到河流圖的ComboBox1_Change()
        .ScreenUpdating = True
    End With
    Sheets("河流圖").Range("A2") = ""       '113/06/12 將(1)移到這裡，避免先執行(2)，造成河流圖的ComboBox1_Change()誤判
    Application.EnableEvents = True

End Sub

Sub 設定圖表座標軸大小值(SName)
    
    Dim myChart As ChartObject
    Application.ScreenUpdating = False
    
    PB最大值1 = Sheets(SName).[H1]
    PB最小值1 = Sheets(SName).[H2]
    Sheets(SName).Activate
    ActiveSheet.ChartObjects("圖表 1").Activate         '個股股價淨值比河流圖 (P/B band)
    ActiveChart.Axes(xlValue).Select
    With ActiveChart.Axes(xlValue)
        .MinimumScale = PB最小值1
        .MaximumScale = PB最大值1
        .MinorUnitIsAuto = True
        .MajorUnitIsAuto = True
        .Crosses = xlAutomatic
        .ReversePlotOrder = False
        .ScaleType = xlLinear
        .DisplayUnit = xlNone
    End With
    
    PE最大值1 = Sheets(SName).[G1]
    PE最小值1 = Sheets(SName).[G2]
    Sheets(SName).Activate
    ActiveSheet.ChartObjects("圖表 2").Activate         '個股本益比河流圖 (P/E band)
    ActiveChart.Axes(xlValue).Select
    With ActiveChart.Axes(xlValue)
        .MinimumScale = PE最小值1
        .MaximumScale = PE最大值1
        .MinorUnitIsAuto = True
        .MajorUnitIsAuto = True
        .Crosses = xlAutomatic
        .ReversePlotOrder = False
        .ScaleType = xlLinear
        .DisplayUnit = xlNone
    End With

'    For Each myChart In ActiveSheet.ChartObjects
'        myChart.Chart.Refresh
'    Next myChart
    Application.ScreenUpdating = True
    
'    Sheets(SName).Activate
'    Debug.Print ActiveSheet.ChartObjects(1).Name
'    Debug.Print ActiveSheet.ChartObjects(2).Name
'    Debug.Print ActiveSheet.ChartObjects(3).Name
'    Debug.Print ActiveSheet.ChartObjects(4).Name
    
End Sub

Sub Output2word(SName)

    Dim theTable As Variant
    Dim theSheet As Variant

    EndRow = Sheets(SName).Cells(Rows.Count, "B").End(xlUp).Row
    theSheet = Application.Transpose(Sheets(SName).Range("A2:A" & EndRow).Value)
    theTable = Application.Transpose(Sheets(SName).Range("B2:B" & EndRow).Value)
  
   '執行WORD，新增DOC
    Set theWord = CreateObject("Word.Application")
    With theWord
        .Visible = True
        Set theDOC = .Documents.Add
        
       '設定版面邊界
        With theDOC.PageSetup
            .Orientation = xlPortrait
            .TopMargin = theWord.CentimetersToPoints(1)
            .BottomMargin = theWord.CentimetersToPoints(1)
            .LeftMargin = theWord.CentimetersToPoints(1)
            .RightMargin = theWord.CentimetersToPoints(1)
        End With
    End With
        
   '貼六大財務指標評等
    For i = LBound(theTable) To UBound(theTable)
        Sheets(theSheet(i)).Activate
        Sheets(theSheet(i)).Range(Split(theTable(i), ":")(0)).Activate
        ActiveSheet.Range(theTable(i)).CopyPicture
        theWord.Selection.TypeParagraph     '換行
        theWord.Selection.TypeParagraph
        theWord.Selection.Paste
    Next i
    
    
   'WORD存檔
    theTickerCorp = Sheets("六大財務指標評等").Range("B1").Value
    theDOC.SaveAs ThisWorkbook.Path & "\" & theTickerCorp & "_" & Format(Now, "yyyy-mm-dd_hhmm")
        
End Sub


Sub Query_TAIEX_YTV_NEW(StockNo, SName)
'109/9/13 改寫"年度交易資訊"程式，改善抓取速度

    Dim URL As String
    Dim arrData(1 To 60, 1 To 10)
    
'    SName = "年度交易資訊"
'    StockNo = "1101"
    With Sheets(SName)
         .Visible = True
'         .Cells.ClearContents
         .Range("A1:I200").ClearContents    '109/03/26
         '.Activate
    End With
    
   '以 Late binding 建立物件
    Set XMLHTTP = CreateObject("MSXML2.XMLHTTP.6.0")
'    theURL = "https://www.twse.com.tw/exchangeReport/FMNPTK?response=html&stockNo=" & StockNo
    theURL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK?response=html&stockNo=" & StockNo       ' 112/03/24 因應證交所網站更版更改網址
   '採用XMLHTTP OBJECT
    With XMLHTTP
        .Open "GET", theURL, False
        .send
    End With
     While XMLHTTP.Status <> 200 Or XMLHTTP.readyState <> 4
        DoEvents
    Wend
    
   '資料轉寫 - html的表格(table)
'    Dim html As Object
    Set html = CreateObject("htmlfile")
    html.body.innerHTML = XMLHTTP.responseText
    
   '取得全部表格物件
    Set divs = html.getElementsByTagName("div")
    tmpHead = divs(0).innerText
    
    '設為手動重算及暫停螢幕更新
    With Application
        .Calculation = xlCalculationManual
        .ScreenUpdating = False
    End With

'    If Left(tmpHead, 3) = "很抱歉" Then
    If tmpHead = "" Then         ' 112/03/25 因應證交所網站更版更改網址，上櫃股票是空值""
        Set XMLHTTP = Nothing
        Set html = Nothing
        Sheets(SName).Select
        Range("A1") = tmpHead
        Sheets("EPS預估與估價").Select
    Else
        Set tables = html.getElementsByTagName("table")
'        Set h2s = html.getElementsByTagName("h2")
'        tmpHead = h2s(0).innerText
    
       '逐一轉寫全部表格物件
        
        wr = 1
        For Each Table In tables
            If Table.innerText Like "*成交股數*" Then
                For Each theRow In Table.Rows
                    wc = 1
                    For Each theCell In theRow.Cells
                        'SName.Cells(wr, wc) = theCell.innerText
                        arrData(wr, wc) = theCell.innerText
                        wc = wc + 1
                    Next
                    wr = wr + 1
                    'SName.Cells(wr, "A").Activate
                Next
            End If
        Next
       
        Set XMLHTTP = Nothing
        Set html = Nothing
        
        Sheets(SName).Select
        Range("A1").Resize(wr, wc) = arrData
        Sheets("EPS預估與估價").Select
    End If
    
   '恢復自動重算及螢幕更新
    With Application
        .Calculation = xlCalculationAutomatic
        .ScreenUpdating = True
    End With
        
End Sub

Sub WebQuery_TAIEX_YTV(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
         .Visible = True
'         .Cells.ClearContents
         .Range("A1:I200").ClearContents    '109/03/26
         '.Activate
         .Range("A1") = "個股年成交資訊"
    End With
    
    'URL = "http://www.twse.com.tw/ch/trading/exchange/FMNPTK/FMNPTKMAIN.php"
'    URL = "https://www.twse.com.tw/exchangeReport/FMNPTK?response=html&stockNo=" & StockNo
    URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK?response=html&stockNo=" & StockNo  ' 112/03/24 因應證交所網站更版更改網址
    'thePOST = "download=&CO_ID=" & StockNo
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A1"))
        .Name = "TAIEX_YTV"
        '.PostText = thePOST
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "1"
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub WebQuery_TAIEX_YTV2(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
         .Visible = True
'         .Cells.ClearContents
         .Range("A1:I200").ClearContents    '109/03/26
         '.Activate
    End With
    
'    URL = "https://www.tpex.org.tw/web/stock/statistics/monthly/print_st42.php?l=zh-tw"
'    thePOST = "stk_no=" & StockNo
    
    URL = "https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock?code=" & StockNo & "&id=&response=html"     ' 113/11/05 因應證交所網站更版更改網址
    On Error Resume Next    '113/11/05 因應櫃買中心網站更版更改網址，修正碰到上市股票時會有錯誤訊息的問題
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A1"))
        .Name = "TAIEX_YTV2"
'        .PostText = thePOST
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "1"                        '僅抓第1個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub WebQuery_TAIEX_YTV2_bck(StockNo, SName)
' 113/11/05 因應櫃買中心網站更版更改網址，不再使用
    Dim URL As String
    
    With Sheets(SName)
         .Visible = True
'         .Cells.ClearContents
         .Range("A1:I200").ClearContents    '109/03/26
         '.Activate
    End With
    
'    URL = "https://www.tpex.org.tw/web/stock/statistics/monthly/st42.php?l=zh-tw"
    URL = "https://www.tpex.org.tw/web/stock/statistics/monthly/result_st42.php?l=zh-tw"
       
    thePOST = "input_stock_code=" & StockNo
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A1"))
        .Name = "TAIEX_YTV2m"
        .PostText = thePOST
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "1,3"                        '僅抓第1及第3個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub MergeYTV_New(SName, SName_上市, SName_上櫃)

    Dim arrData(10, 1 To 9)
    
    With Sheets(SName)
         .Visible = True
         .Cells.ClearContents
         '.Activate
    End With
    PriceL = 0
    PriceM = 0
    PriceH = 0
    
    arrData(0, 1) = "年度"
    arrData(0, 2) = "成交股數(仟)"
    arrData(0, 3) = "成交金額(仟元)"
    arrData(0, 4) = "成交筆數(仟)"
    arrData(0, 5) = "最高價"
    arrData(0, 6) = "日期"
    arrData(0, 7) = "最低價"
    arrData(0, 8) = "日期"
    arrData(0, 9) = "收盤平均價"
    
    '111/1/5 4739 上櫃+上市
    'If Sheets(SName_上市).Range("A2") <> "" And Sheets(SName_上市).Range("A3") <> "查無資料！" Then
    If Sheets(SName_上市).Range("A1") = "年度" Then
        lastrow = Sheets(SName_上市).Range("A1").End(xlDown).Row
        If (lastrow > 11) Then   '判斷資料>10筆
            For i = 0 To 9
                For j = 1 To 9
                    If j = 2 Or j = 3 Or j = 4 Then
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j) / 1000
                    Else
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j)
                    End If
                Next j
            Next i
        ElseIf (lastrow = 11) Then   '判斷資料=10筆
            For i = 0 To 8
                For j = 1 To 9
                    If j = 2 Or j = 3 Or j = 4 Then
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j) / 1000
                    Else
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j)
                    End If
                Next j
            Next i
            If Sheets(SName_上櫃).Range("A4") <> "年度" Then
                 For j = 1 To 9
                    If j = 2 Or j = 3 Or j = 4 Then
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j) / 1000
                    Else
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j)
                    End If
                Next j
            Else '判斷上市櫃有同一年度資料兩筆資料
                arrData(i + 1, 1) = Sheets(SName_上市).Range("A2") '年度
                arrData(i + 1, 2) = Sheets(SName_上市).Range("B2") / 1000 + Sheets(SName_上櫃).Range("B5")  '成交股數
                arrData(i + 1, 3) = Sheets(SName_上市).Range("C2") / 1000 + Sheets(SName_上櫃).Range("C5")  '成交金額
                arrData(i + 1, 4) = Sheets(SName_上市).Range("D2") / 1000 + Sheets(SName_上櫃).Range("D5")  '成交筆數
                If Sheets(SName_上市).Range("E2") > Sheets(SName_上櫃).Range("E5") Then '判斷最高價
                    arrData(i + 1, 5) = Sheets(SName_上市).Range("E2")
                    arrData(i + 1, 6) = Sheets(SName_上市).Range("F2")
                Else
                    arrData(i + 1, 5) = Sheets(SName_上櫃).Range("E5")
                    arrData(i + 1, 6) = Sheets(SName_上櫃).Range("F5")
                End If
'                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Then '判斷最低價
                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Or Sheets(SName_上櫃).Range("G5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->盤中最低價[G5]=""的狀況
                    arrData(i + 1, 7) = Sheets(SName_上市).Range("G2")
                    arrData(i + 1, 8) = Sheets(SName_上市).Range("H2")
                Else
                    arrData(i + 1, 7) = Sheets(SName_上櫃).Range("G5")
                    arrData(i + 1, 8) = Sheets(SName_上櫃).Range("H5")
                End If
                If Sheets(SName_上櫃).Range("I5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->收盤平均價[I5]=""的狀況
                    arrData(i + 1, 9) = Sheets(SName_上市).Range("I2")
                Else
                    arrData(i + 1, 9) = (Sheets(SName_上市).Range("I2") + Sheets(SName_上櫃).Range("I5")) / 2 '收盤平均價
                End If
            End If
        Else '判斷資料<10筆
             For i = 0 To lastrow - 3
                For j = 1 To 9
                    If j = 2 Or j = 3 Or j = 4 Then
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j) / 1000
                    Else
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j)
                    End If
                Next j
            Next i
            If Sheets(SName_上櫃).Range("A4") <> "年度" Then
                 For j = 1 To 9
                    If j = 2 Or j = 3 Or j = 4 Then
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j) / 1000
                    Else
                        arrData(i + 1, j) = Sheets(SName_上市).Cells(lastrow - i, j)
                    End If
                Next j
            Else '判斷上市櫃有同一年度資料兩筆資料
                arrData(i + 1, 1) = Sheets(SName_上市).Range("A2") '年度
                arrData(i + 1, 2) = Sheets(SName_上市).Range("B2") / 1000 + Sheets(SName_上櫃).Range("B5") '成交股數
                arrData(i + 1, 3) = Sheets(SName_上市).Range("C2") / 1000 + Sheets(SName_上櫃).Range("C5") '成交金額
                arrData(i + 1, 4) = Sheets(SName_上市).Range("D2") / 1000 + Sheets(SName_上櫃).Range("D5") '成交筆數
                If Sheets(SName_上市).Range("E2") > Sheets(SName_上櫃).Range("E5") Then '判斷最高價
                    arrData(i + 1, 5) = Sheets(SName_上市).Range("E2")
                    arrData(i + 1, 6) = Sheets(SName_上市).Range("F2")
                Else
                    arrData(i + 1, 5) = Sheets(SName_上櫃).Range("E5")
                    arrData(i + 1, 6) = Sheets(SName_上櫃).Range("F5")
                End If
'                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Then '判斷最低價
                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Or Sheets(SName_上櫃).Range("G5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->盤中最低價[G5]=""的狀況
                    arrData(i + 1, 7) = Sheets(SName_上市).Range("G2")
                    arrData(i + 1, 8) = Sheets(SName_上市).Range("H2")
                Else
                    arrData(i + 1, 7) = Sheets(SName_上櫃).Range("G5")
                    arrData(i + 1, 8) = Sheets(SName_上櫃).Range("H5")
                End If
                If Sheets(SName_上櫃).Range("I5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->收盤平均價[I5]=""的狀況
                    arrData(i + 1, 9) = Sheets(SName_上市).Range("I2")
                Else
                    arrData(i + 1, 9) = (Sheets(SName_上市).Range("I2") + Sheets(SName_上櫃).Range("I5")) / 2 '收盤平均價
                End If
            End If
            If Sheets(SName_上櫃).Range("A5") <> "" Then '110/4/4 例外判斷年度交易資訊(上櫃)無股價資料的狀況
                lastrow2 = 10 - (lastrow - 1) '年度交易資訊(上櫃)可copy筆數(已扣除上市同一年度的筆資料)
                r = i + 1
                 For i = 0 To lastrow2 - 1
                    For j = 1 To 9
                        arrData(r + i + 1, j) = Sheets(SName_上櫃).Cells(i + 6, j)
                    Next j
                Next i
            End If
        End If
    Else
        lastrow = Sheets(SName_上櫃).Range("A4").End(xlDown).Row
        If lastrow > 14 Then
            lastrow = 15
        End If
        Sheets(SName).Range("A1") = Sheets(SName_上櫃).Range("B1")
        Sheets(SName).Range("B1") = Sheets(SName_上櫃).Range("A1")
        If lastrow > 5 Then
            lastrow2 = lastrow - 5      '年度交易資訊(上櫃)可copy筆數
             For i = 0 To lastrow2 - 1
                For j = 1 To 9
                    arrData(i + 1, j) = Sheets(SName_上櫃).Cells(i + 6, j)
                Next j
            Next i
        End If
    End If
    Sheets(SName).Range("A2").Resize(11, 9) = arrData
'    Sheets(SName).Activate
'    Sheets(SName).Range("A1").Select
'    Application.CutCopyMode = False
'    Sheets("EPS預估與估價").Activate

End Sub

Sub MergeYTV(SName, SName_上市, SName_上櫃)

    With Sheets(SName)
         .Visible = True
         .Cells.ClearContents
         '.Activate
    End With
    PriceL = 0
    PriceM = 0
    PriceH = 0
    'Sheets(SName_上市).Range("A1:I2").Copy
    'Sheets(SName).Range("A1:I2").PasteSpecial xlPasteValues
    Sheets(SName).Range("A2") = "年度"
    Sheets(SName).Range("B2") = "成交股數(仟)"
    Sheets(SName).Range("C2") = "成交金額(仟元)"
    Sheets(SName).Range("D2") = "成交筆數(仟)"
    Sheets(SName).Range("E2") = "最高價"
    Sheets(SName).Range("F2") = "日期"
    Sheets(SName).Range("G2") = "最低價"
    Sheets(SName).Range("H2") = "日期"
    Sheets(SName).Range("I2") = "收盤平均價"

    'If Sheets(SName_上市).Range("A2") <> "" And Sheets(SName_上市).Range("A3") <> "查無資料！" Then
    If Sheets(SName_上市).Range("A1") = "年度" Then
        lastrow = Sheets(SName_上市).Range("A1").End(xlDown).Row
        If (lastrow > 11) Then   '判斷資料>10筆
            For i = 0 To 9
                Sheets(SName_上市).Range("A" & lastrow - i & ":I" & lastrow - i).Copy
                Sheets(SName).Range("A" & i + 3).PasteSpecial xlPasteValues
                Sheets(SName).Range("B" & i + 3) = Sheets(SName).Range("B" & i + 3) / 1000
                Sheets(SName).Range("C" & i + 3) = Sheets(SName).Range("C" & i + 3) / 1000
                Sheets(SName).Range("D" & i + 3) = Sheets(SName).Range("D" & i + 3) / 1000
            Next i
        ElseIf (lastrow = 11) Then   '判斷資料=10筆
            For i = 0 To 8
                Sheets(SName_上市).Range("A" & lastrow - i & ":I" & lastrow - i).Copy
                Sheets(SName).Range("A" & i + 3).PasteSpecial xlPasteValues
                Sheets(SName).Range("B" & i + 3) = Sheets(SName).Range("B" & i + 3) / 1000
                Sheets(SName).Range("C" & i + 3) = Sheets(SName).Range("C" & i + 3) / 1000
                Sheets(SName).Range("D" & i + 3) = Sheets(SName).Range("D" & i + 3) / 1000
            Next i
            'i = i - 1 'i=9，故-1
            If Sheets(SName_上櫃).Range("A4") <> "年度" Then
                Sheets(SName_上市).Range("A2:I2").Copy      '第10筆
                Sheets(SName).Range("A12").PasteSpecial xlPasteValues
                Sheets(SName).Range("B12") = Sheets(SName).Range("B12") / 1000
                Sheets(SName).Range("C12") = Sheets(SName).Range("C12") / 1000
                Sheets(SName).Range("D12") = Sheets(SName).Range("D12") / 1000
            Else '判斷上市櫃有同一年度資料兩筆資料
                Sheets(SName).Range("A12") = Sheets(SName_上市).Range("A2") '年度
                Sheets(SName).Range("B12") = Sheets(SName_上市).Range("B2") / 1000 + Sheets(SName_上櫃).Range("B5") '成交股數
                Sheets(SName).Range("C12") = Sheets(SName_上市).Range("C2") / 1000 + Sheets(SName_上櫃).Range("C5") '成交金額
                Sheets(SName).Range("D12") = Sheets(SName_上市).Range("D2") / 1000 + Sheets(SName_上櫃).Range("D5") '成交筆數
'                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Then '判斷最低價
                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Or Sheets(SName_上櫃).Range("G5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->盤中最低價[G5]=""的狀況
                    Sheets(SName).Range("G12") = Sheets(SName_上市).Range("G2")
                    Sheets(SName).Range("H12") = Sheets(SName_上市).Range("H2")
                Else
                    Sheets(SName).Range("G12") = Sheets(SName_上櫃).Range("G5")
                    Sheets(SName).Range("H12") = Sheets(SName_上櫃).Range("H5")
                End If
                If Sheets(SName_上市).Range("E2") > Sheets(SName_上櫃).Range("E5") Then '判斷最高價
                    Sheets(SName).Range("E12") = Sheets(SName_上市).Range("E2")
                    Sheets(SName).Range("F12") = Sheets(SName_上市).Range("F2")
                Else
                    Sheets(SName).Range("E12") = Sheets(SName_上櫃).Range("E5")
                    Sheets(SName).Range("F12") = Sheets(SName_上櫃).Range("F5")
                End If
                If Sheets(SName_上櫃).Range("I5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->收盤平均價[I5]=""的狀況
                    Sheets(SName).Range("I12") = Sheets(SName_上市).Range("I2")
                Else
                    Sheets(SName).Range("I12") = (Sheets(SName_上市).Range("I2") + Sheets(SName_上櫃).Range("I5")) / 2 '收盤平均價
                End If
            End If
        Else '判斷資料<10筆
            For i = 0 To lastrow - 3
                Sheets(SName_上市).Range("A" & lastrow - i & ":I" & lastrow - i).Copy
                Sheets(SName).Range("A" & i + 3).PasteSpecial xlPasteValues
                Sheets(SName).Range("B" & i + 3) = Sheets(SName).Range("B" & i + 3) / 1000
                Sheets(SName).Range("C" & i + 3) = Sheets(SName).Range("C" & i + 3) / 1000
                Sheets(SName).Range("D" & i + 3) = Sheets(SName).Range("D" & i + 3) / 1000
            Next i
            'i = i - 1
            If Sheets(SName_上櫃).Range("A4") <> "年度" Then
                Sheets(SName_上市).Range("A2:I2").Copy
                Sheets(SName).Range("A" & i + 3).PasteSpecial xlPasteValues
                Sheets(SName).Range("B" & i + 3) = Sheets(SName).Range("B" & i + 3) / 1000
                Sheets(SName).Range("C" & i + 3) = Sheets(SName).Range("C" & i + 3) / 1000
                Sheets(SName).Range("D" & i + 3) = Sheets(SName).Range("D" & i + 3) / 1000
            Else '判斷上市櫃有同一年度資料兩筆資料
                Sheets(SName).Range("A" & i + 3) = Sheets(SName_上市).Range("A2") '年度
                Sheets(SName).Range("B" & i + 3) = Sheets(SName_上市).Range("B2") / 1000 + Sheets(SName_上櫃).Range("B5") '成交股數
                Sheets(SName).Range("C" & i + 3) = Sheets(SName_上市).Range("C2") / 1000 + Sheets(SName_上櫃).Range("C5") '成交金額
                Sheets(SName).Range("D" & i + 3) = Sheets(SName_上市).Range("D2") / 1000 + Sheets(SName_上櫃).Range("D5") '成交筆數
'                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Then '判斷最低價
                If Sheets(SName_上市).Range("G2") < Sheets(SName_上櫃).Range("G5") Or Sheets(SName_上櫃).Range("G5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->盤中最低價[G5]=""的狀況
                    Sheets(SName).Range("G" & i + 3) = Sheets(SName_上市).Range("G2")
                    Sheets(SName).Range("H" & i + 3) = Sheets(SName_上市).Range("H2")
                Else
                    Sheets(SName).Range("G" & i + 3) = Sheets(SName_上櫃).Range("G5")
                    Sheets(SName).Range("H" & i + 3) = Sheets(SName_上櫃).Range("H5")
                End If
                If Sheets(SName_上市).Range("E2") > Sheets(SName_上櫃).Range("E5") Then '判斷最高價
                    Sheets(SName).Range("E" & i + 3) = Sheets(SName_上市).Range("E2")
                    Sheets(SName).Range("F" & i + 3) = Sheets(SName_上市).Range("F2")
                Else
                    Sheets(SName).Range("E" & i + 3) = Sheets(SName_上櫃).Range("E5")
                    Sheets(SName).Range("F" & i + 3) = Sheets(SName_上櫃).Range("F5")
                End If
                If Sheets(SName_上櫃).Range("I5") = "" Then '110/4/4 例外判斷年度交易資訊(上櫃)->收盤平均價[I5]=""的狀況
                    Sheets(SName).Range("I" & i + 3) = Sheets(SName_上市).Range("I2")
                Else
                    Sheets(SName).Range("I" & i + 3) = (Sheets(SName_上市).Range("I2") + Sheets(SName_上櫃).Range("I5")) / 2 '收盤平均價
                End If
            End If
            If Sheets(SName_上櫃).Range("A5") <> "" Then '110/4/4 例外判斷年度交易資訊(上櫃)無股價資料的狀況
                lastrow2 = 10 - (lastrow - 1) '年度交易資訊(上櫃)可copy筆數(已扣除上市同一年度的筆資料)
                For j = 0 To lastrow2 - 1
                    Sheets(SName_上櫃).Range("A" & j + 6 & ":I" & j + 6).Copy
                    Sheets(SName).Range("A" & j + i + 4).PasteSpecial xlPasteValues
                Next j
            End If
        End If
    Else
        Sheets(SName).Range("A1") = Sheets(SName_上櫃).Range("B1")
        Sheets(SName).Range("B1") = Sheets(SName_上櫃).Range("A1")
        lastrow = Sheets(SName_上櫃).Range("A4").End(xlDown).Row
'        If Sheets(SName_上櫃).Range("A5") = Range("D3") + 1 Then      '上櫃有最新年度但未滿一年交易資訊，需額外判斷
'            If lastrow > 14 Then
'                lastrow = 14
'            End If
'            Sheets(SName_上櫃).Range("A5" & ":I" & lastrow).Copy
'            Sheets(SName).Range("A3" & ":I" & lastrow - 2).PasteSpecial xlPasteValues
'        Else
            If lastrow > 14 Then
                lastrow = 15
            End If
            If lastrow > 5 Then
                Sheets(SName_上櫃).Range("A6" & ":I" & lastrow).Copy
                Sheets(SName).Range("A3").PasteSpecial xlPasteValues
            End If
'        End If
    End If
    Sheets(SName).Activate
    Sheets(SName).Range("A1").Select
    Application.CutCopyMode = False
    Sheets("EPS預估與估價").Activate

End Sub

Sub TWSE_PRICE_DAY2YEAR_cnYES(SName)

    '將當年度上市「個股日成交資訊」轉為當年度「個股年度成交資訊」
    Set theCell = Sheets("年度交易資訊").Cells(Rows.Count, "A").End(xlUp).Offset(1)
    theRow = theCell.Row
    If Sheets("年度交易資訊").Range("A2") <> "" Then        '110/7/6 例外處理查無「年度成交資訊」
        '109/5/2 新增判斷每年第一交易日，但尚未有日收盤價資料時的例外狀況
        If Not Sheets(SName).[A2].Value = "" And Sheets(SName).[O2].Value - 1 = Sheets("年度交易資訊").Range("A" & theRow - 1).Value + 1911 Then
            With Sheets("年度交易資訊")
    '             theRow = theCell.Row
                 lastrow = Sheets("股價(日)").Range("U2")
                .Cells(theRow, "A").Value = Year(Date) - 1911
                .Cells(theRow, "B").Value = Application.Sum(Sheets(SName).Range("H2:H" & lastrow))      '成交股數(仟)
                .Cells(theRow, "C").Value = Application.Sum(Sheets(SName).Range("I2:I" & lastrow))      '成交金額(仟元)
    '            .Cells(theRow, "D").Value =                                                                                                                               '無成交筆數(仟)
                .Cells(theRow, "E").Value = Application.Max(Sheets(SName).Range("C2:C" & lastrow))      '最高價
                .Cells(theRow, "G").Value = Application.Min(Sheets(SName).Range("D2:D" & lastrow))      '最低價
                .Cells(theRow, "I").Value = Round(Application.Average(Sheets(SName).Range("E2:E" & lastrow)), 2)    '收盤平均價
            End With
        End If
    Else
        If Not Sheets(SName).[A2].Value = "" Then       '110/7/6 例外處理查無「年度成交資訊」
            With Sheets("年度交易資訊")
    '             theRow = theCell.Row
                 lastrow = Sheets("股價(日)").Range("U2")
                .Cells(theRow, "A").Value = Year(Date) - 1911
                .Cells(theRow, "B").Value = Application.Sum(Sheets(SName).Range("H2:H" & lastrow))      '成交股數(仟)
                .Cells(theRow, "C").Value = Application.Sum(Sheets(SName).Range("I2:I" & lastrow))      '成交金額(仟元)
    '            .Cells(theRow, "D").Value =                                                                                                                               '無成交筆數(仟)
                .Cells(theRow, "E").Value = Application.Max(Sheets(SName).Range("C2:C" & lastrow))      '最高價
                .Cells(theRow, "G").Value = Application.Min(Sheets(SName).Range("D2:D" & lastrow))      '最低價
                .Cells(theRow, "I").Value = Round(Application.Average(Sheets(SName).Range("E2:E" & lastrow)), 2)    '收盤平均價
            End With
        End If
    End If

End Sub

Sub MoneyDJ_財報三表_New(URL, SName)

    Dim oXML As Object
    Set oXML = CreateObject("MSXML2.XMLHTTP.6.0")
    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")
    With oXML
        .Open "GET", URL, False
        .send
        oHTML.body.innerHTML = convertraw(.responseBody, "Big5")
'        Debug.Print oHTML.body.innerHTML
    End With

'    Dim arrData(1 To 120, 1 To 10)
    Dim arrData(1 To 130, 1 To 10)      '111/2/14 金控、證券類股的CFQ科目較多，修正加大陣列長度
'    Set oTable = oHTML.getElementsByTagName("table")(1)
    Set oTable = oHTML.getElementById("oMainTable")     '111/1/4
    Set oRows = oTable.getElementsByTagName("div")      '資料Row-->"div" Tag
    
    arrData(1, 1) = Split(Split(oRows(1).innerText, vbCrLf)(0), " ")(0)     '財報名稱
    arrData(2, 1) = Split(oRows(1).innerText, vbCrLf)(1)        '單位
    wr = 3
    For Each oRow In oRows
        If oRow.className = "table-row" Then        '111/1/4
            Set oCells = oRow.getElementsByTagName("span")      '資料Cell-->"span" Tag
            wc = 1
'            spanTag_init = 1
            For Each oCell In oCells
                arrData(wr, wc) = oCell.innerText
                wc = wc + 1
            Next
'            If wc <> spanTag_init Then      '判斷有無"span" Tag
                wr = wr + 1
        End If
    Next
    Sheets(SName).Range("A3").Resize(wr, wc) = arrData

    Set oHTML = Nothing
    Set oXML = Nothing

End Sub

Sub MoneyDJ_財務比率_New(URL, SName)

    Dim oXML As Object
    Set oXML = CreateObject("MSXML2.XMLHTTP.6.0")
    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")
    With oXML
        .Open "GET", URL, False
        .send
        oHTML.body.innerHTML = convertraw(.responseBody, "Big5")
'        Debug.Print oHTML.body.innerHTML
    End With

    Dim arrData(1 To 100, 1 To 10)
'    Set oTable = oHTML.getElementsByTagName("table")(1)
    Set oTable = oHTML.getElementById("oMainTable")     '111/1/4
    Set oRows = oTable.getElementsByTagName("div")  '資料Row-->"div" Tag
    wr = 1
    For Each oRow In oRows
'        If Left(oRow.innerHTML, 10) = "<div class" Or Left(oRow.innerHTML, 10) = "<DIV class" Then
        If UCase(Left(oRow.innerHTML, 10)) = "<DIV CLASS" Then      '111/1/4
            If wr = 1 Then  '110/12/26 對部分excel版本，或不明狀況之財報名稱進行例外處理
                If Split(oRow.innerText, vbCrLf)(0) = "" Then
                    arrData(wr, 1) = Split(Split(oRow.innerText, vbCrLf)(1), " ")(0)  '財報名稱
                    wr = wr + 1
                Else    '110/12/26
                    arrData(wr, 1) = Split(oRow.innerText, " ")(0)    '財報名稱
                    wr = wr + 1
                End If
            Else
                arrData(wr, 1) = Split(oRow.innerText, vbCrLf)(0)   '指標
                wr = wr + 1
                arrData(wr, 1) = Split(oRow.innerText, vbCrLf)(1)   '單位
                wr = wr + 1
            End If
        Else
            If oRow.className = "table-row" Then        '111/1/4
                Set oCells = oRow.getElementsByTagName("span") '資料Cell --> "span" Tag
                wc = 1
'                spanTag_init = 1
                For Each oCell In oCells
                    arrData(wr, wc) = oCell.innerText
                    wc = wc + 1
                Next
'                If wc <> spanTag_init Then      '判斷有無"span" Tag
                    wr = wr + 1
            End If
        End If
    Next
    Sheets(SName).Range("A3").Resize(wr, wc) = arrData

    Set oHTML = Nothing
    Set oXML = Nothing

End Sub

Sub Get_CFQ(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A3").End(xlDown).Row
        .Range("A2:I" & lastrow).ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zc3/zc3_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zc3/zc3_" & StockNo & ".djhtm"
    End If
    
    MoneyDJ_財報三表_New URL, SName     '110/12/25 因應MoneyDJ 在聖誕節前夕大改版
         
'    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
'        .Name = "CFQ"
'        .FieldNames = True
'        .RowNumbers = False
'        .FillAdjacentFormulas = False
'        .PreserveFormatting = False
'        .RefreshOnFileOpen = False
'        .BackgroundQuery = True
''        .RefreshStyle = xlInsertDeleteCells
'        .RefreshStyle = xlOverwriteCells
'        .SavePassword = False
'        .SaveData = False
'        .AdjustColumnWidth = False
'        .RefreshPeriod = 0
'        .WebSelectionType = xlSpecifiedTables
'        .WebFormatting = xlWebFormattingNone
'        .WebTables = "2"                        '僅抓第2個表格
'        .WebPreFormattedTextToColumns = True
'        .WebConsecutiveDelimitersAsOne = True
'        .WebSingleBlockTextImport = False
'        .WebDisableDateRecognition = True         '關閉日期辨識
'        .Refresh BackgroundQuery:=False
'        .Delete
'    End With
    
End Sub

Sub Get_FRQ(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
'        lastrow = Sheets(SName).Range("A3").End(xlDown).Row
'        .Range("A2:I" & lastrow).ClearContents
        .Range("A2:I102").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zcr/zcr_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zcr/zcr_" & StockNo & ".djhtm"
    End If
    
    MoneyDJ_財務比率_New URL, SName     '110/12/25 因應MoneyDJ 在聖誕節前夕大改版
    
'    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
'        .Name = "FRQ"
'        .FieldNames = True
'        .RowNumbers = False
'        .FillAdjacentFormulas = False
'        .PreserveFormatting = False
'        .RefreshOnFileOpen = False
'        .BackgroundQuery = True
''        .RefreshStyle = xlInsertDeleteCells
'        .RefreshStyle = xlOverwriteCells
'        .SavePassword = False
'        .SaveData = False
'        .AdjustColumnWidth = False
'        .RefreshPeriod = 0
'        .WebSelectionType = xlSpecifiedTables
'        .WebFormatting = xlWebFormattingNone
'        .WebTables = "2"                        '僅抓第2個表格
'        .WebPreFormattedTextToColumns = True
'        .WebConsecutiveDelimitersAsOne = True
'        .WebSingleBlockTextImport = False
'        .WebDisableDateRecognition = True         '關閉日期辨識
'        .Refresh BackgroundQuery:=False
'        .Delete
'    End With
    
End Sub

Sub Get_ISQ(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A3").End(xlDown).Row
        .Range("A2:I" & lastrow).ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zcq/zcq_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zcq/zcq_" & StockNo & ".djhtm"
    End If
      
    MoneyDJ_財報三表_New URL, SName     '110/12/25 因應MoneyDJ 在聖誕節前夕大改版
    
'    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
'        .Name = "ISQ"
'        .FieldNames = True
'        .RowNumbers = False
'        .FillAdjacentFormulas = False
'        .PreserveFormatting = False
'        .RefreshOnFileOpen = False
'        .BackgroundQuery = True
''        .RefreshStyle = xlInsertDeleteCells
'        .RefreshStyle = xlOverwriteCells
'        .SavePassword = False
'        .SaveData = False
'        .AdjustColumnWidth = False
'        .RefreshPeriod = 0
'        .WebSelectionType = xlSpecifiedTables
'        .WebFormatting = xlWebFormattingNone
'        .WebTables = "2"                        '僅抓第2個表格
'        .WebPreFormattedTextToColumns = True
'        .WebConsecutiveDelimitersAsOne = True
'        .WebSingleBlockTextImport = False
'        .WebDisableDateRecognition = True         '關閉日期辨識
'        .Refresh BackgroundQuery:=False
'        .Delete
'    End With
    
End Sub
Sub Get_BSQ(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A3").End(xlDown).Row
        .Range("A2:I" & lastrow).ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zcp/zcpa/zcpa_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zcp/zcpa/zcpa_" & StockNo & ".djhtm"
    End If
      
    MoneyDJ_財報三表_New URL, SName     '110/12/25 因應MoneyDJ 在聖誕節前夕大改版
    
'    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
'        .Name = "BSQ"
'        .FieldNames = True
'        .RowNumbers = False
'        .FillAdjacentFormulas = False
'        .PreserveFormatting = False
'        .RefreshOnFileOpen = False
'        .BackgroundQuery = True
''        .RefreshStyle = xlInsertDeleteCells
'        .RefreshStyle = xlOverwriteCells
'        .SavePassword = False
'        .SaveData = False
'        .AdjustColumnWidth = False
'        .RefreshPeriod = 0
'        .WebSelectionType = xlSpecifiedTables
'        .WebFormatting = xlWebFormattingNone
'        .WebTables = "2"                        '僅抓第2個表格
'        .WebPreFormattedTextToColumns = True
'        .WebConsecutiveDelimitersAsOne = True
'        .WebSingleBlockTextImport = False
'        .WebDisableDateRecognition = True         '關閉日期辨識
'        .Refresh BackgroundQuery:=False
'        .Delete
'    End With
    
End Sub

Sub Get_BASIC(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        .Range("A2:I40").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zca/zca_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zca/zca_" & StockNo & ".djhtm"
    End If
      
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
        .Name = "BASIC"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "3"                        '僅抓第3個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub Get_OPQ(StockNo, SName)
'經營績效
    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A3").End(xlDown).Row
        .Range("A2:H" & lastrow).ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zce/zcd_" & StockNo & ".djhtm"
    Else
        URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zce/zcd_" & StockNo & ".djhtm"
    End If
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
        .Name = "OPQ"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "2"                        '僅抓第2個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub Get_EPQ(StockNo, SName)
'獲利能力
    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A6").End(xlDown).Row
'         .Range("A2:J" & lastrow).ClearContents    '券商之"獲利能力分析季報"新增欄位，[EPQ]->K欄新增EPS(元)，原K欄移至L欄
        .Range("A2:K" & lastrow).ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zce/zce_" & StockNo & ".djhtm"
    Else
        URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zce/zce_" & StockNo & ".djhtm"
    End If
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
        .Name = "EPQ"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "2"                        '僅抓第2個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub Get_REV(StockNo, SName)
'月營收
    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        .Range("A:G").ClearContents
        '.Activate
        theHost = GetHost(.Range("N1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zch/zch_" & StockNo & ".djhtm"
    Else
        URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zch/zch_" & StockNo & ".djhtm"
    End If
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A1"))
        .Name = "REV"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "3"                        '僅抓第3個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

Sub Get_股利(StockNo, SName)
'獲利能力
    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A6").End(xlDown).Row
        .Range("A2:I200").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zcc/zcc_" & StockNo & ".djhtm"
    Else
        URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcc/zcc_" & StockNo & ".djhtm"
    End If
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
        .Name = "股利"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "2"                        '僅抓第2個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

'Sub Get_法人持股(StockNo, SName, Start_yyyymd, End_yyyymd)
Sub Get_法人持股(StockNo, SName)        '110/5/22改採網址"近20日"選項，而不自己判斷日期
'三大法人持股及買賣超
    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        .Range("A2:K200").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
'    https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a=2330&c=2021-1-4&d=2021-1-8
'    https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a=2330&b=3   '   近20日
'    URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a=" & StockNo & "&c=" & Start_yyyymd & "&d=" & End_yyyymd
    URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a=" & StockNo & "&b=3"     '110/5/12修改為抓取近20日
    
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("A3"))
        .Name = "法人持股"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "2"                        '僅抓第2個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
'    三大法人Stock = Left(Sheets(SName).Range("A5"), Len(Sheets(SName).Range("A5")) - 6) & " "       '110/6/13多一個空白是Sheets("EPS預估與估價").Range("A1")也有多一空白
'    If Sheets(SName).Range("A16") <> Sheets(SName).Range("AA16") Or 三大法人Stock <> Sheets("EPS預估與估價").Range("A1") Then        '110/6/13 修正bug，額外判斷三大法人Stock
'    110/6/20 不判斷if，修正[外資投信]按"更新"時，日股價或三大法人數據未同步更新的問題
        '從證券網站抓
        Dim arrData(1 To 520, 1 To 8)
'        Application.StatusBar = "開始抓取股價(日)2，請稍待..."
        MoneyDJ_TW_PRICE_New "股價(日)2", StockNo, "D"      '111/1/8 改用陣列，加快執行速度
        With Sheets("股價(日)2")
            RowEnd = .Range("S1").End(xlDown).Row
            If .Range("S" & RowEnd) > .Range("S2") Then       '110/3/29 例外判斷個股股歷史價格只有當年度的情形
                LastYear = .Range("S" & RowEnd) - 1
            Else
                LastYear = .Range("S" & RowEnd)
            End If
            RowBgn = WorksheetFunction.Match(LastYear, .Range("S:S"), 0)
            wr = 1
            For i = RowEnd To RowBgn Step -1
                wc = 21
                arrData(wr, 1) = WorksheetFunction.Text(.Cells(i, 20), "yyyy/mm/dd")      '日期
                For j = 2 To 5
                    arrData(wr, j) = .Cells(i, wc)      '開盤    最高    最低    收盤
                    wc = wc + 1
                Next
                If i <> 2 Then
                    arrData(wr, 6) = .Cells(i, 24) - .Cells(i - 1, 24)      '漲跌
                    arrData(wr, 7) = (.Cells(i, 24) - .Cells(i - 1, 24)) / .Cells(i - 1, 24)    '漲%
                Else
                    arrData(wr, 6) = ""      '漲跌
                    arrData(wr, 7) = ""    '漲%
                End If
                arrData(wr, 8) = .Cells(i, 25)          '成交量
                wr = wr + 1
            Next
            Sheets("股價(日)").Range("A2:J520").ClearContents
            Sheets("股價(日)").Range("A2:A520").NumberFormatLocal = "@"    '轉為文字格式，避免鉅亨網抓過後又變為日期格式
            Sheets("股價(日)").Range("A2").Resize(520, 8) = arrData        'copy到[股價(日)]工作表
        End With
'    End If
    
End Sub

Sub Get_data_from_GoodInfo_董監持股(StockNo, SName)

    Dim arrData(1 To 500, 1 To 26)  '113/3/19 50->500
    Dim oXML As Object
'    Set oXML = CreateObject("MSXML2.XMLHTTP")
    Set oXML = CreateObject("WinHttp.WinHttpRequest.5.1")   '113/4/30 用於set cookies，解決網站保護機制
    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")

    Set tmpSName = Sheets(SName)
    With tmpSName
        .Visible = True
        .Cells.ClearContents
        '.Activate
    End With

    '-----------------------------------------------113/4/30
    isProxy = Sheets("大戶持股").Range("M2")
    thePROXY = Sheets("大戶持股").Range("M3")
    '-----------------------------------------------
'    theURL = "https://goodinfo.tw/StockInfo/StockDirectorSharehold.asp?STOCK_ID=" & StockNo
    theURL = "https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID=" & StockNo    '113/6/11 網站變更網址
    With oXML
        .Open "GET", theURL, 0
        '---------------------------------------------------------------------------------------------------------------
        .setRequestHeader "Cookie", "SCREEN_SIZE=WIDTH=1139&HEIGHT=640"     '113/4/30 解決網站保護機制
        .Option(4) = 13056
        If isProxy = "Y" Then
            .SetProxy 2, thePROXY
        End If
        '---------------------------------------------------------------------------------------------------------------
        .send
        oHTML.body.innerHTML = convertraw(.responseBody, "UTF-8")
'        Debug.Print oHTML.body.innerHTML
    End With
    
    Set tables = oHTML.getElementsByTagName("table")
    wr = 1
    For Each Table In tables
        If Table.innerText Like "*發行*張數*(萬張)*" And Not Table.innerText Like "*回到首頁*" Then
            For Each theRow In Table.Rows
                wc = 1
                For Each theCell In theRow.Cells
                    'tmpSName.Cells(wr, wc) = theCell.innerText
                    arrData(wr, wc) = theCell.innerText
                    wc = wc + 1
                Next
                wr = wr + 1
                'tmpSName.Cells(wr, "A").Activate
            Next
        End If
    Next
    
    Set oHTML = Nothing
    Set oXML = Nothing
    
    Application.ScreenUpdating = False   '畫面不會跳動

    tmpSName.Select
    Range("A1").Resize(wr, wc) = arrData
    
    '調整表頭
    Range("D2:R2").Select
    Selection.Cut
    Range("F2").Select
    ActiveSheet.Paste
    Range("A2:C2").Select
    Selection.Cut
    Range("B2").Select
    ActiveSheet.Paste
    Range("A1").Select
    tmpSName.[U1] = tmpSName.[G1]
    tmpSName.[G1] = ""
    tmpSName.[P1] = tmpSName.[F1]
    tmpSName.[F1] = ""
    tmpSName.[K1] = tmpSName.[E1]
    tmpSName.[E1] = ""
    tmpSName.[F1] = tmpSName.[D1]
    tmpSName.[D1] = ""
    tmpSName.[E1] = tmpSName.[C1]
    tmpSName.[C1] = ""
   
    '刪除多餘列
    EndRow = Cells(Rows.Count, "A").End(xlUp).Row
    If WorksheetFunction.CountA(Range("U3:U" & EndRow)) <> EndRow - 1 Then
        Range("U3:U" & EndRow).SpecialCells(xlCellTypeBlanks).EntireRow.Delete
    End If
    
    Application.ScreenUpdating = True
    
    Sheets("董監持股").Select

End Sub

Sub Get_data_from_GoodInfo_大戶持股(StockNo, SName, theShareHoldType, theCol, isProxy)

    Dim arrData(1 To 500, 1 To 21)      '111/1/24 欄位20->21，113/3/19 200->500
    Dim oXML As Object
    Set oXML = CreateObject("WinHttp.WinHttpRequest.5.1")
    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")
    
    thePROXY = Range("M3")
    
    Set tmpSName = Sheets(SName)
    If theCol = 1 Then
        With tmpSName
            .Visible = True
            lastrow = Sheets(SName).Cells(1, 3).End(xlDown).Row
            .Range("A1:BT" & lastrow).ClearContents
            '.Activate
        End With
    End If
    
'    theURL = "https://goodinfo.tw/StockInfo/EquityDistributionClassHis.asp?STOCK_ID=" & StockNo & "&CHT_CAT=WEEK&STEP=DATA&DISPLAY_CAT=" & theShareHoldType
'    theURL = "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STOCK_ID=" & StockNo & "&CHT_CAT=WEEK&STEP=DATA&DISPLAY_CAT=" & theShareHoldType     '111/1/24 Goodinfo更改網址
'    theURL = "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STOCK_ID=" & StockNo & "&CHT_CAT=WEEK&PRICE_ADJ=F&STEP=DATA&DISPLAY_CAT=" & theShareHoldType     '113/4/30 新增參數PRICE_ADJ=F
'    =====113/11/10 因應Goodinfo網址調整參數，修正抓取[大戶持股]之資料筆數不足54筆(週)問題======
    EndDate = Format(Now, "yyyy-mm-dd")
    StartDate = (Left(EndDate, 4) - 2) & Right(EndDate, 6)
    theURL = "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STEP=DATA&STOCK_ID=" & StockNo & "&CHT_CAT=WEEK&PRICE_ADJ=F&SHEET=" & theShareHoldType & "&START_DT=" & StartDate & "&END_DT=" & EndDate
'    ================================================================
    With oXML
        .Open "POST", theURL, 0
        .setRequestHeader "referer", "https://goodinfo.tw/tw/EquityDistributionClassHis.asp?STOCK_ID=" & StockNo
        .setRequestHeader "user-agent", "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Mobile Safari/537.36"
        .setRequestHeader "Cookie", "SCREEN_SIZE=WIDTH=1139&HEIGHT=640"     '113/4/30 解決網站保護機制
        .Option(4) = 13056
        If isProxy = "Y" Then
            .SetProxy 2, thePROXY
        End If
        .send ""

        oHTML.body.innerHTML = convertraw(.responseBody, "UTF-8")
'        Debug.Print oHTML.body.innerHTML
    End With

    Set tables = oHTML.getElementsByTagName("table")
    
    wr = 1
    For Each Table In tables
        If Table.innerText Like "*各持股等級股東之*" Then
            For Each theRow In Table.Rows
                wc = 1
                For Each theCell In theRow.Cells
                    'tmpSName.Cells(wr, wc) = theCell.innerText
                    arrData(wr, wc) = theCell.innerText
                    wc = wc + 1
                Next
                wr = wr + 1
                'tmpSName.Cells(wr, "A").Activate
            Next
        End If
    Next
    
    Set oHTML = Nothing
    Set oXML = Nothing
    
    Application.ScreenUpdating = False   '畫面不會跳動

    tmpSName.Select
    Cells(1, theCol).Resize(wr - 1, wc - 1) = arrData
    
    '調整表頭，111/1/24 Goodinfo更改欄位
'    Range(Cells(2, theCol), Cells(2, 17 + theCol)).Select
    Range(Cells(2, 3 + theCol), Cells(2, 17 + theCol)).Select
    Selection.Cut
'    Cells(2, 2 + theCol).Select
    Cells(2, 6 + theCol).Select
    ActiveSheet.Paste
    Range(Cells(2, theCol), Cells(2, 2 + theCol)).Select
    Selection.Cut
    Cells(2, 2 + theCol).Select
    ActiveSheet.Paste
'    Range(Cells(1, 3 + theCol), Cells(1, 3 + theCol)).Select
'    Selection.Cut
'    Cells(1, 5 + theCol).Select
'    ActiveSheet.Paste
    Cells(2, 5 + theCol) = Cells(1, 3 + theCol)
    Cells(1, 6 + theCol) = Cells(1, 4 + theCol)
    Cells(1, 3 + theCol) = ""
    Cells(1, 4 + theCol) = ""
    Range("A1").Select
   
    '刪除多餘列
    If theCol = 53 Then
        EndRow = Cells(Rows.Count, "A").End(xlUp).Row
        If WorksheetFunction.CountA(Range("A3:A" & EndRow)) <> EndRow - 1 Then
            Range("T3:T" & EndRow).SpecialCells(xlCellTypeBlanks).EntireRow.Delete
        End If
    End If
    
    Sheets("大戶持股").Select
    Application.ScreenUpdating = True
    
End Sub

Sub Get_StockNews_from_MoneyLink(StockNo, SName)
'Sub Get_StockNews()
'   StockNo = "1806"
'   SName = "個股新聞"

    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        lastrow = Sheets(SName).Range("A4").End(xlDown).Row
        .Range("A4:E" & lastrow).ClearContents
        '.Activate
    End With
    
    Dim oXML As Object
    Set oXML = CreateObject("MSXML2.XMLHTTP")
    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")

    With oXML
        .Open "GET", "https://ww2.money-link.com.tw/TWStock/StockNews.aspx?SymId=" & StockNo, 0
        .send ""
        oHTML.body.innerHTML = convertraw(.responseBody, "UTF-8")
'        Debug.Print oHTML.body.innerHTML
    End With

    Dim oTable As Object, oRow As Object, oCell As Object
    Dim i As Integer, j As Integer

    Application.ScreenUpdating = False
    
    Set oTable = oHTML.getElementsByTagName("table")(3)
    Set theDates_Contents = oTable.getElementsByTagName("div")
    i = 4
    For Each theDate In theDates_Contents
        If theDate.className = "NewsDate" Then
'            Debug.Print theDate.innerText
            NewsDate = Split(theDate.innerText, " ")
            Cells(i, 1).Value = NewsDate(0)
            Cells(i, 2).Value = NewsDate(1)
            Cells(i, 3).Value = NewsDate(2)
            i = i + 1
        End If
    Next
    
    Set theLinks = oTable.getElementsByTagName("a")
    i = 4
    For Each theLink In theLinks
        If theLink.innerText = "(詳全文)" Then
            NewsLink = Replace(theLink.href, "about:", "https://ww2.money-link.com.tw")
'            Debug.Print NewsLink
'            Debug.Print theLink.Title
            ActiveSheet.Hyperlinks.Add anchor:=Cells(i, 4), Address:=NewsLink, TextToDisplay:=theLink.Title
            i = i + 1
        End If
    Next
    
    i = 4
    For Each theContent In theDates_Contents
        If theContent.className = "NewsContent" Then
'            Debug.Print theContent.innerText
             Cells(i, 5).Value = theContent.innerText
            i = i + 1
        End If
    Next
    
    Application.ScreenUpdating = True
   
    Set oHTML = Nothing
    Set oXML = Nothing
End Sub

Sub Get_StockNews_from_Yahoo(StockNo, SName)
    '110/9/23 因應Yahoo更版寫法，但日期/時間 (以x 天前／x 小時前 表示)暫無法抓取，之後找到方法再改吧！
    
    lastrow = Sheets(SName).Range("A4").End(xlDown).Row
    
    Dim oXML As Object
    Set oXML = CreateObject("MSXML2.XMLHTTP")

    Dim oHTML As Object
    Set oHTML = CreateObject("HTMLFile")

    With oXML
'        .Open "GET", "https://tw.stock.yahoo.com/q/h?s=" & StockNo, 0
        .Open "GET", "https://tw.stock.yahoo.com/quote/" & StockNo & "/news", 0
        .send ""

        oHTML.body.innerHTML = convertraw(.responseBody, "UTF-8")
'        Debug.Print oHTML.body.innerHTML
    End With
   
    Application.ScreenUpdating = False

    Set theNews = oHTML.getElementById("module-wafer-stream")
    Set theLis = theNews.getElementsByTagName("li")
    i = lastrow + 1
    For Each theLi In theLis
'        Debug.Print theLi.innerText
        NewsData = Split(theLi.innerText, vbCrLf)
        Ub = UBound(NewsData)
        If Ub >= 7 Then
            If NewsData(3) <> "" Then
                Cells(i, 1).Value = NewsData(3)     '來源
                Cells(i, 4).Value = NewsData(5)     '新聞標題
                If Len(NewsData(7)) > 130 Then
                    Cells(i, 5).Value = Left(NewsData(7), 120) & "...(詳全文)"   '內文摘要
                Else
                    Cells(i, 5).Value = NewsData(7)     '內文摘要
                End If
                i = i + 1
            ElseIf NewsData(6) <> "" Then
                Cells(i, 1).Value = NewsData(6)     '來源
                Cells(i, 4).Value = NewsData(8)     '新聞標題
                If Len(NewsData(10)) > 130 Then
                    Cells(i, 5).Value = Left(NewsData(10), 120) & "...(詳全文)"    '內文摘要
                Else
                    Cells(i, 5).Value = NewsData(10)     '內文摘要
                End If
                i = i + 1
            End If
        End If
    Next
    Set theLinks = theNews.getElementsByTagName("a")
    i = lastrow + 1
    For Each theLink In theLinks
'        Debug.Print theLink.innerText
'        Debug.Print theLink.hostname
        If theLink.hostname = "tw.stock.yahoo.com" And Len(theLink.innerText) > 3 Then
            NewsLink = theLink.href
'            Debug.Print NewsLink
            ActiveSheet.Hyperlinks.Add anchor:=Cells(i, 4), Address:=NewsLink
            i = i + 1
        End If
    Next
    
    Application.ScreenUpdating = True

    Set oHTML = Nothing
    Set oXML = Nothing

End Sub

Function convertraw(rawdata, char)

    Dim rawstr
    Set rawstr = CreateObject("adodb.stream")
    With rawstr
        .Type = 1
        .Mode = 3
        .Open
        .Write rawdata
        .Position = 0
        .Type = 2
        .Charset = char
        convertraw = .ReadText
        .Close
    End With
    Set rawstr = Nothing

End Function

Sub Get_BASIC_三大法人(StockNo, SName)

    Dim URL As String
    
    With Sheets(SName)
        .Visible = True
'        .Cells.ClearContents
        .Range("AR2:AZ40").ClearContents
        '.Activate
        theHost = GetHost(.Range("F1"))      '109/04/28 可選擇不同券商
    End With
    
    If theHost <> "" Then
        URL = theHost & "/z/zc/zca/zca_" & StockNo & ".djhtm"
    Else
        URL = "http://jsjustweb.jihsun.com.tw/z/zc/zca/zca_" & StockNo & ".djhtm"
    End If
      
    With Sheets(SName).QueryTables.Add(Connection:="URL;" & URL, Destination:=Sheets(SName).Range("AR3"))
        .Name = "BASIC_三大法人"
        .FieldNames = True
        .RowNumbers = False
        .FillAdjacentFormulas = False
        .PreserveFormatting = False
        .RefreshOnFileOpen = False
        .BackgroundQuery = True
'        .RefreshStyle = xlInsertDeleteCells
        .RefreshStyle = xlOverwriteCells
        .SavePassword = False
        .SaveData = False
        .AdjustColumnWidth = False
        .RefreshPeriod = 0
        .WebSelectionType = xlSpecifiedTables
        .WebFormatting = xlWebFormattingNone
        .WebTables = "3"                        '僅抓第3個表格
        .WebPreFormattedTextToColumns = True
        .WebConsecutiveDelimitersAsOne = True
        .WebSingleBlockTextImport = False
        .WebDisableDateRecognition = True         '關閉日期辨識
        .Refresh BackgroundQuery:=False
        .Delete
    End With
    
End Sub

